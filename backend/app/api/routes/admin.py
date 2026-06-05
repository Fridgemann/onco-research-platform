import hashlib
import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from pydantic import BaseModel, EmailStr

from app.api.dependencies import AdminUser
from app.core.config import settings
from app.core.database import get_db
from app.core.security import encrypt_field, decrypt_field
from app.models.audit_log import AuditAction
from app.models.user import User, UserRole
from app.models.researcher_invite import ResearcherInvite, ResearcherInviteStatus
from app.services.audit import write_audit_log
from app.services.email import send_researcher_invite_email

INVITE_EXPIRY_DAYS = 7

router = APIRouter(prefix="/admin", tags=["admin"])


class UserSummary(BaseModel):
    id: str
    role: UserRole
    is_active: bool
    is_verified: bool
    failed_login_attempts: int
    locked_until: datetime | None
    created_at: datetime
    last_login: datetime | None


class DeactivateResponse(BaseModel):
    message: str


class RoleChangeRequest(BaseModel):
    role: UserRole


class RoleChangeResponse(BaseModel):
    message: str
    role: UserRole


@router.get("/users", response_model=list[UserSummary])
async def list_users(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    users = (await db.scalars(select(User).order_by(User.created_at.desc()))).all()
    return [
        UserSummary(
            id=u.id,
            role=u.role,
            is_active=u.is_active,
            is_verified=u.is_verified,
            failed_login_attempts=u.failed_login_attempts,
            locked_until=u.locked_until,
            created_at=u.created_at,
            last_login=u.last_login,
        )
        for u in users
    ]


@router.patch("/users/{user_id}/deactivate", response_model=DeactivateResponse)
async def deactivate_user(
    user_id: str,
    request: Request,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account.")

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if not user.is_active:
        raise HTTPException(status_code=409, detail="User is already deactivated.")

    user.is_active = False
    user.updated_at = datetime.now(timezone.utc)

    await write_audit_log(
        db,
        action=AuditAction.USER_DEACTIVATED,
        user_id=current_user.id,
        resource_type="user",
        resource_id=user_id,
        request=request,
    )

    return DeactivateResponse(message="User deactivated successfully.")


@router.patch("/users/{user_id}/role", response_model=RoleChangeResponse)
async def change_user_role(
    user_id: str,
    body: RoleChangeRequest,
    request: Request,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    if body.role == UserRole.ADMIN:
        raise HTTPException(status_code=400, detail="Cannot assign admin role via this endpoint.")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role.")

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.role = body.role
    user.updated_at = datetime.now(timezone.utc)

    await write_audit_log(
        db,
        action=AuditAction.ROLE_CHANGED,
        user_id=current_user.id,
        resource_type="user",
        resource_id=user_id,
        detail=f"role={body.role.value}",
        request=request,
    )

    return RoleChangeResponse(message="User role updated successfully.", role=body.role)


# ── Researcher invite schemas ────────────────────────────────────────────────

class ResearcherInviteRequest(BaseModel):
    email: EmailStr


class ResearcherInviteResponse(BaseModel):
    invite_id: str
    token: str | None = None  # omitted in production — sent via email only
    expires_at: datetime
    message: str


class ResearcherInviteListItem(BaseModel):
    id: str
    invited_email: str
    status: ResearcherInviteStatus
    invited_by: str
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None


# ── Researcher invite helpers ────────────────────────────────────────────────

def _hash_email(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── Researcher invite routes ─────────────────────────────────────────────────

@router.post("/invites/researcher", response_model=ResearcherInviteResponse, status_code=201)
async def create_researcher_invite(
    request: Request,
    body: ResearcherInviteRequest,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    email_hash = _hash_email(body.email)
    now = datetime.now(timezone.utc)

    existing = await db.execute(
        select(ResearcherInvite).where(
            ResearcherInvite.invited_email_hash == email_hash,
            ResearcherInvite.status == ResearcherInviteStatus.PENDING,
            ResearcherInvite.expires_at > now,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A pending researcher invite already exists for this email.")

    plain_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(plain_token)
    expires_at = now + timedelta(days=INVITE_EXPIRY_DAYS)

    invite = ResearcherInvite(
        invited_email_encrypted=encrypt_field(body.email.lower()),
        invited_email_hash=email_hash,
        token_hash=token_hash,
        invited_by=current_user.id,
        created_at=now,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.flush()

    await write_audit_log(
        db, AuditAction.RESEARCHER_INVITED,
        user_id=current_user.id,
        resource_type="researcher_invite",
        resource_id=invite.id,
        request=request,
    )

    await send_researcher_invite_email(body.email.lower(), plain_token)

    return ResearcherInviteResponse(
        invite_id=invite.id,
        token=plain_token if settings.APP_ENV != "production" else None,
        expires_at=expires_at,
        message="Researcher invite created.",
    )


@router.get("/invites/researcher", response_model=list[ResearcherInviteListItem])
async def list_researcher_invites(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ResearcherInvite).order_by(ResearcherInvite.created_at.desc())
    )
    invites = result.scalars().all()
    return [
        ResearcherInviteListItem(
            id=inv.id,
            invited_email=decrypt_field(inv.invited_email_encrypted),
            status=inv.status,
            invited_by=inv.invited_by,
            created_at=inv.created_at,
            expires_at=inv.expires_at,
            accepted_at=inv.accepted_at,
        )
        for inv in invites
    ]


@router.delete("/invites/researcher/{invite_id}", status_code=204)
async def revoke_researcher_invite(
    request: Request,
    invite_id: str,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ResearcherInvite).where(ResearcherInvite.id == invite_id)
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite.status != ResearcherInviteStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending invites can be revoked.")

    invite.status = ResearcherInviteStatus.REVOKED

    await write_audit_log(
        db, AuditAction.RESEARCHER_INVITE_REVOKED,
        user_id=current_user.id,
        resource_type="researcher_invite",
        resource_id=invite.id,
        request=request,
    )
