import hashlib
import os
import urllib.parse
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.core.database import get_db
from app.core.security import decrypt_field, encrypt_field, encrypt_bytes, decrypt_bytes
from app.models.audit_log import AuditAction
from app.models.dataset import Dataset, DatasetStatus
from app.models.workspace import WorkspaceMember, MemberRole
from app.schemas.dataset import (
    ALLOWED_CONTENT_TYPES,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    DatasetDeleteResponse,
    DatasetResponse,
)
from app.services.audit import write_audit_log
from app.services import storage

router = APIRouter(
    prefix="/workspaces/{workspace_id}/datasets",
    tags=["Datasets"],
)


async def _require_member(
    workspace_id: str, user_id: str, db: AsyncSession
) -> WorkspaceMember:
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=403, detail="You are not a member of this workspace.")
    return member


def _dataset_to_response(dataset: Dataset) -> DatasetResponse:
    return DatasetResponse(
        id=dataset.id,
        workspace_id=dataset.workspace_id,
        filename=decrypt_field(dataset.filename_encrypted),
        content_type=dataset.content_type,
        file_size=dataset.file_size,
        description=dataset.description,
        uploaded_by=dataset.uploaded_by,
        created_at=dataset.created_at,
    )


@router.post("", response_model=DatasetResponse, status_code=201)
async def upload_dataset(
    request: Request,
    workspace_id: str,
    file: UploadFile,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    description: str | None = Form(None),
):
    await _require_member(workspace_id, current_user.id, db)

    # Validate extension
    filename = file.filename or ""
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Validate content type
    allowed_mimes = ALLOWED_CONTENT_TYPES.get(ext)
    if file.content_type and allowed_mimes and file.content_type not in allowed_mimes:
        raise HTTPException(
            status_code=400,
            detail=f"Content-Type '{file.content_type}' is not allowed for {ext} files.",
        )

    # Read file into memory
    data = await file.read()

    # Check size
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {MAX_FILE_SIZE // (1024 * 1024)} MB.",
        )

    # Magic bytes check for xlsx
    if ext == ".xlsx" and not data[:4] == b"PK\x03\x04":
        raise HTTPException(status_code=400, detail="File does not appear to be a valid .xlsx file.")

    # Build dataset record
    dataset_id = str(uuid.uuid4())
    object_key = f"{workspace_id}/{dataset_id}"

    filename_hash = hashlib.sha256(filename.encode()).hexdigest()

    # Encrypt and upload to MinIO BEFORE writing to DB
    encrypted_data = encrypt_bytes(data)
    await storage.upload_object(object_key, encrypted_data, "application/octet-stream")

    dataset = Dataset(
        id=dataset_id,
        workspace_id=workspace_id,
        uploaded_by=current_user.id,
        filename_encrypted=encrypt_field(filename),
        filename_hash=filename_hash,
        content_type=file.content_type or next(iter(allowed_mimes), None) or "application/octet-stream",
        file_size=len(data),
        object_key=object_key,
        description=description,
    )
    db.add(dataset)
    await db.flush()

    await write_audit_log(
        db,
        AuditAction.DATASET_UPLOADED,
        user_id=current_user.id,
        resource_type="dataset",
        resource_id=dataset.id,
        request=request,
    )

    return _dataset_to_response(dataset)


@router.get("", response_model=list[DatasetResponse])
async def list_datasets(
    workspace_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _require_member(workspace_id, current_user.id, db)

    result = await db.execute(
        select(Dataset).where(
            Dataset.workspace_id == workspace_id,
            Dataset.is_deleted == False,  # noqa: E712
        )
    )
    datasets = result.scalars().all()
    return [_dataset_to_response(d) for d in datasets]


@router.get("/{dataset_id}")
async def download_dataset(
    request: Request,
    workspace_id: str,
    dataset_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _require_member(workspace_id, current_user.id, db)

    result = await db.execute(
        select(Dataset).where(
            Dataset.id == dataset_id,
            Dataset.workspace_id == workspace_id,
            Dataset.is_deleted == False,  # noqa: E712
        )
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found.")

    encrypted_data = await storage.download_object(dataset.object_key)
    data = decrypt_bytes(encrypted_data)

    original_filename = decrypt_field(dataset.filename_encrypted)
    quoted_filename = urllib.parse.quote(original_filename)

    await write_audit_log(
        db,
        AuditAction.DATASET_DOWNLOADED,
        user_id=current_user.id,
        resource_type="dataset",
        resource_id=dataset.id,
        request=request,
    )

    return Response(
        content=data,
        media_type=dataset.content_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"dataset{os.path.splitext(original_filename)[1]}\"; "
                f"filename*=UTF-8''{quoted_filename}"
            )
        },
    )


@router.delete("/{dataset_id}", response_model=DatasetDeleteResponse)
async def delete_dataset(
    request: Request,
    workspace_id: str,
    dataset_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    member = await _require_member(workspace_id, current_user.id, db)

    result = await db.execute(
        select(Dataset).where(
            Dataset.id == dataset_id,
            Dataset.workspace_id == workspace_id,
            Dataset.is_deleted == False,  # noqa: E712
        )
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found.")

    is_owner = member.role == MemberRole.OWNER
    is_uploader = dataset.uploaded_by == current_user.id
    if not (is_owner or is_uploader):
        raise HTTPException(
            status_code=403,
            detail="Only the workspace owner or the uploader can delete this dataset.",
        )

    dataset.is_deleted = True
    dataset.deleted_at = datetime.now(timezone.utc)
    dataset.status = DatasetStatus.DELETED

    await write_audit_log(
        db,
        AuditAction.DATASET_DELETED,
        user_id=current_user.id,
        resource_type="dataset",
        resource_id=dataset.id,
        request=request,
    )

    return DatasetDeleteResponse(message="Dataset deleted successfully.")
