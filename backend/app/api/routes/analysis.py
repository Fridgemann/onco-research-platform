import io
import json
import logging
import re

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.models.audit_log import AuditAction
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import decrypt_bytes
from app.models.analysis_job import AnalysisJob
from app.models.dataset import Dataset, DatasetStatus
from app.models.workspace import WorkspaceMember
from app.schemas.analysis import (
    AnalysisJobCreate,
    AnalysisJobResponse,
    KMPreflightRequest,
    KMPreflightResponse,
)
from app.services import storage
from app.services.audit import write_audit_log
from app.tasks.analysis import AnalysisValidationError, _km_preflight, run_analysis_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces/{workspace_id}/datasets/{dataset_id}/analysis", tags=["analysis"])
jobs_router = APIRouter(prefix="/analysis", tags=["analysis"])


async def _get_dataset_or_404(
    workspace_id: str,
    dataset_id: str,
    user_id: str,
    db: AsyncSession,
) -> Dataset:
    member = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")

    dataset = await db.scalar(
        select(Dataset).where(
            Dataset.id == dataset_id,
            Dataset.workspace_id == workspace_id,
            Dataset.is_deleted == False,
        )
    )
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    return dataset


def _job_to_response(job: AnalysisJob) -> AnalysisJobResponse:
    return AnalysisJobResponse(
        id=job.id,
        dataset_id=job.dataset_id,
        workspace_id=job.workspace_id,
        requested_by=job.requested_by,
        job_type=job.job_type,
        status=job.status,
        parameters=json.loads(job.parameters) if job.parameters else None,
        result=json.loads(job.result) if job.result else None,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


@router.post("", response_model=AnalysisJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_analysis_job(
    workspace_id: str,
    dataset_id: str,
    body: AnalysisJobCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    dataset = await _get_dataset_or_404(workspace_id, dataset_id, current_user.id, db)

    job = AnalysisJob(
        dataset_id=dataset.id,
        workspace_id=workspace_id,
        requested_by=current_user.id,
        job_type=body.job_type,
        parameters=json.dumps(body.parameters or {}),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    await write_audit_log(
        db,
        action=AuditAction.ANALYSIS_STARTED,
        user_id=current_user.id,
        resource_type="analysis_job",
        resource_id=job.id,
        detail=f"job_type={job.job_type} dataset_id={dataset_id}",
    )

    run_analysis_task.delay(job.id)

    return _job_to_response(job)


@router.post("/km-preflight", response_model=KMPreflightResponse)
@limiter.limit("30/minute")
async def km_preflight(
    workspace_id: str,
    dataset_id: str,
    body: KMPreflightRequest,
    request: Request,          # required by the rate limiter
    response: Response,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Validate a Kaplan-Meier censoring configuration against a dataset and
    return row/event/censoring counts plus per-status-value mapping roles,
    without running the analysis.

    Same workspace-member authorization as analysis submission. The dataset is
    downloaded, decrypted, and parsed off the event loop. Status values are
    returned to the authorized member for the mapping UI but are never placed
    in logs, audit detail, errors, or the URL. `ready` here is advisory only —
    the Celery run always re-validates via _km_prepare, so it cannot be
    bypassed by a direct client.
    """
    dataset = await _get_dataset_or_404(workspace_id, dataset_id, current_user.id, db)

    raw = await storage.download_object(dataset.object_key)

    def _parse_and_preflight():
        data = decrypt_bytes(raw)
        df = pd.read_csv(io.StringIO(data.decode("utf-8")), index_col=False)
        df = df.loc[:, ~df.columns.str.match(r"^Unnamed: \d+$")]
        return _km_preflight(df, body.model_dump())

    try:
        result = await run_in_threadpool(_parse_and_preflight)
    except AnalysisValidationError as exc:
        # Developer-authored, value-free message — safe to surface.
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception:
        # Never leak dataset-derived content; log without cell values.
        logger.error("KM preflight failed for dataset %s (sanitized)", dataset_id)
        raise HTTPException(status_code=422, detail="Could not process dataset for preflight.")

    # Audit the data-access action. Detail carries no status values.
    await write_audit_log(
        db,
        action=AuditAction.ANALYSIS_PREFLIGHTED,
        user_id=current_user.id,
        resource_type="dataset",
        resource_id=dataset_id,
        detail=f"km_preflight dataset_id={dataset_id}",
    )

    response.headers["Cache-Control"] = "no-store"
    return result


@jobs_router.get("/{job_id}", response_model=AnalysisJobResponse)
async def get_analysis_job(
    job_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    job = await db.scalar(select(AnalysisJob).where(AnalysisJob.id == job_id))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    member = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == job.workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")

    return _job_to_response(job)


@jobs_router.get("", response_model=list[AnalysisJobResponse])
async def list_analysis_jobs(
    workspace_id: str,  # query param: GET /api/analysis?workspace_id=xxx
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    member = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")

    jobs = (
        await db.scalars(
            select(AnalysisJob)
            .where(AnalysisJob.workspace_id == workspace_id)
            .order_by(AnalysisJob.created_at.desc())
        )
    ).all()

    return [_job_to_response(j) for j in jobs]
