from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from pydantic import BaseModel

from app.api.dependencies import AdminUser
from app.core.database import get_db
from app.models.audit_log import AuditAction
from app.models.user import User, UserRole
from app.services.audit import write_audit_log

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
