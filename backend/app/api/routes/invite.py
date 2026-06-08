import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.core.security import encrypt_field, decrypt_field
from app.models.workspace import WorkspaceMember, MemberRole
from app.models.workspace_invite import WorkspaceInvite, InviteStatus
from app.models.audit_log import AuditAction
from app.models.user import User
from app.schemas.invite import (
    InviteCreateRequest,
    InviteCreateResponse,
    InviteResponse,
    InviteAcceptRequest,
    InviteAcceptResponse,
    InviteDeclineRequest,
    InviteDeclineResponse,
)
from app.services.audit import write_audit_log
from app.services.email import send_invite_email
from app.api.dependencies import CurrentUser
from app.api.routes.workspace import _get_workspace_or_404, _require_owner

workspace_invite_router = APIRouter(prefix="/workspaces", tags=["Invites"])
invite_router = APIRouter(prefix="/invites", tags=["Invites"])

INVITE_EXPIRY_DAYS = 7


def _hash_email(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@workspace_invite_router.post("/{workspace_id}/invites", response_model=InviteCreateResponse, response_model_exclude_none=True, status_code=201)
async def create_invite(
    request: Request,
    workspace_id: str,
    body: InviteCreateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    workspace = await _get_workspace_or_404(workspace_id, db)
    await _require_owner(workspace, current_user)

    email_hash = _hash_email(body.email)

    # Check: invitee is not already a member
    existing_member = await db.execute(
        select(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            User.email_hash == email_hash,
        )
    )
    if existing_member.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member of this workspace.")

    # Check: no existing pending (non-expired) invite for this email
    now = datetime.now(timezone.utc)
    existing_invite = await db.execute(
        select(WorkspaceInvite).where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.invited_email_hash == email_hash,
            WorkspaceInvite.status == InviteStatus.PENDING,
            WorkspaceInvite.expires_at > now,
        )
    )
    if existing_invite.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A pending invite already exists for this email.")

    plain_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(plain_token)
    expires_at = now + timedelta(days=INVITE_EXPIRY_DAYS)

    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        invited_email_encrypted=encrypt_field(body.email.lower()),
        invited_email_hash=email_hash,
        token_hash=token_hash,
        invited_by=current_user.id,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.flush()

    await write_audit_log(
        db, AuditAction.COLLABORATOR_INVITED,
        user_id=current_user.id,
        resource_type="workspace_invite",
        resource_id=invite.id,
        request=request,
    )

    await send_invite_email(body.email.lower(), plain_token, workspace.name)

    return InviteCreateResponse(
        invite_id=invite.id,
        token=plain_token if settings.APP_ENV != "production" else None,
        expires_at=expires_at,
        message="Invite created.",
    )


@workspace_invite_router.get("/{workspace_id}/invites", response_model=list[InviteResponse])
async def list_invites(
    workspace_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    workspace = await _get_workspace_or_404(workspace_id, db)
    await _require_owner(workspace, current_user)

    result = await db.execute(
        select(WorkspaceInvite)
        .where(WorkspaceInvite.workspace_id == workspace_id)
        .order_by(WorkspaceInvite.created_at.desc())
    )
    invites = result.scalars().all()

    return [
        InviteResponse(
            id=inv.id,
            workspace_id=inv.workspace_id,
            invited_email=decrypt_field(inv.invited_email_encrypted),
            status=inv.status,
            invited_by=inv.invited_by,
            created_at=inv.created_at,
            expires_at=inv.expires_at,
            accepted_at=inv.accepted_at,
        )
        for inv in invites
    ]


@workspace_invite_router.delete("/{workspace_id}/invites/{invite_id}", status_code=204)
async def revoke_invite(
    request: Request,
    workspace_id: str,
    invite_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    workspace = await _get_workspace_or_404(workspace_id, db)
    await _require_owner(workspace, current_user)

    result = await db.execute(
        select(WorkspaceInvite).where(
            WorkspaceInvite.id == invite_id,
            WorkspaceInvite.workspace_id == workspace_id,
        )
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite.status != InviteStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending invites can be revoked.")

    invite.status = InviteStatus.REVOKED

    await write_audit_log(
        db, AuditAction.INVITE_REVOKED,
        user_id=current_user.id,
        resource_type="workspace_invite",
        resource_id=invite.id,
        request=request,
    )


@invite_router.post("/accept", response_model=InviteAcceptResponse)
async def accept_invite(
    request: Request,
    body: InviteAcceptRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    token_hash = _hash_token(body.token)

    result = await db.execute(
        select(WorkspaceInvite).where(WorkspaceInvite.token_hash == token_hash)
    )
    invite = result.scalar_one_or_none()

    # Generic error — don't reveal whether the token exists or why it's invalid
    if not invite:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token.")

    if invite.status != InviteStatus.PENDING:
        raise HTTPException(status_code=400, detail="This invite is no longer valid.")

    if datetime.now(timezone.utc) > invite.expires_at:
        raise HTTPException(status_code=400, detail="This invite has expired.")

    # Email ownership proof: token alone is not enough
    if current_user.email_hash != invite.invited_email_hash:
        raise HTTPException(status_code=403, detail="This invite was sent to a different email address.")

    # Idempotency: handle race where user became a member between invite creation and acceptance
    existing_member = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == invite.workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    if not existing_member.scalar_one_or_none():
        member = WorkspaceMember(
            workspace_id=invite.workspace_id,
            user_id=current_user.id,
            role=MemberRole.COLLABORATOR,
            invited_by=invite.invited_by,
            joined_at=datetime.now(timezone.utc),
        )
        db.add(member)

    invite.status = InviteStatus.ACCEPTED
    invite.accepted_at = datetime.now(timezone.utc)
    await db.flush()

    await write_audit_log(
        db, AuditAction.INVITE_ACCEPTED,
        user_id=current_user.id,
        resource_type="workspace_invite",
        resource_id=invite.id,
        request=request,
    )

    return InviteAcceptResponse(
        message="You have joined the workspace.",
        workspace_id=invite.workspace_id,
        role="collaborator",
    )


@invite_router.post("/decline", response_model=InviteDeclineResponse)
async def decline_invite(
    request: Request,
    body: InviteDeclineRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    token_hash = _hash_token(body.token)

    result = await db.execute(
        select(WorkspaceInvite).where(WorkspaceInvite.token_hash == token_hash)
    )
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token.")

    if invite.status != InviteStatus.PENDING:
        raise HTTPException(status_code=400, detail="This invite is no longer valid.")

    if datetime.now(timezone.utc) > invite.expires_at:
        raise HTTPException(status_code=400, detail="This invite has expired.")

    if current_user.email_hash != invite.invited_email_hash:
        raise HTTPException(status_code=403, detail="This invite was sent to a different email address.")

    invite.status = InviteStatus.DECLINED
    await db.flush()

    await write_audit_log(
        db, AuditAction.INVITE_DECLINED,
        user_id=current_user.id,
        resource_type="workspace_invite",
        resource_id=invite.id,
        request=request,
    )

    return InviteDeclineResponse(message="Invite declined.")
