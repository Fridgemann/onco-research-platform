from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.core.database import get_db
from app.models.workspace import Workspace, WorkspaceMember, MemberRole
from app.models.audit_log import AuditAction
from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse, WorkspaceMemberResponse
from app.services.audit import write_audit_log
from app.api.dependencies import CurrentUser
from app.models.user import User
from app.core.security import decrypt_field

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


async def _get_workspace_or_404(workspace_id: str, db: AsyncSession) -> Workspace:
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return workspace


async def _require_owner(workspace: Workspace, current_user: User) -> None:
    if workspace.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the workspace owner can perform this action.")


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    request: Request,
    body: WorkspaceCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    workspace = Workspace(
        name=body.name,
        description=body.description,
        owner_id=current_user.id,
    )
    db.add(workspace)
    await db.flush()

    # Add owner as a member
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=current_user.id,
        role=MemberRole.OWNER,
        invited_by=current_user.id,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(member)

    await write_audit_log(
        db, AuditAction.WORKSPACE_CREATED,
        user_id=current_user.id,
        resource_type="workspace",
        resource_id=workspace.id,
        request=request,
    )

    return workspace


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == current_user.id)
    )
    return result.scalars().all()


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
async def list_members(
    workspace_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    workspace = await _get_workspace_or_404(workspace_id, db)

    member = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    if not member.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="You are not a member of this workspace.")

    result = await db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.joined_at)
    )
    return [
        WorkspaceMemberResponse(
            id=m.id,
            user_id=m.user_id,
            email=decrypt_field(u.email_encrypted),
            role=m.role,
            invited_by=m.invited_by,
            joined_at=m.joined_at,
        )
        for m, u in result.all()
    ]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    workspace = await _get_workspace_or_404(workspace_id, db)

    member = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    if not member.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="You are not a member of this workspace.")

    return workspace


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    request: Request,
    workspace_id: str,
    body: WorkspaceUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    workspace = await _get_workspace_or_404(workspace_id, db)
    await _require_owner(workspace, current_user)

    if body.name is not None:
        workspace.name = body.name
    if body.description is not None:
        workspace.description = body.description

    await write_audit_log(
        db, AuditAction.WORKSPACE_UPDATED,
        user_id=current_user.id,
        resource_type="workspace",
        resource_id=workspace.id,
        request=request,
    )

    return workspace


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    request: Request,
    workspace_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    workspace = await _get_workspace_or_404(workspace_id, db)
    await _require_owner(workspace, current_user)

    await db.execute(
        WorkspaceMember.__table__.delete().where(
            WorkspaceMember.workspace_id == workspace_id
        )
    )
    await db.delete(workspace)

    await write_audit_log(
        db, AuditAction.WORKSPACE_DELETED,
        user_id=current_user.id,
        resource_type="workspace",
        resource_id=workspace_id,
        request=request,
    )
