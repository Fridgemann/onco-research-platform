from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
import hashlib

from app.core.database import get_db
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    encrypt_field, decrypt_field,
)
from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.user import User, UserRole
from app.models.workspace import WorkspaceMember, MemberRole
from app.models.workspace_invite import WorkspaceInvite, InviteStatus
from app.models.audit_log import AuditAction
from app.schemas.auth import (
    RegisterRequest, LoginRequest,
    TokenResponse, RegisterResponse, UserResponse,
)
from app.services.audit import write_audit_log
from app.api.dependencies import CurrentUser

router = APIRouter(prefix="/auth", tags=["Authentication"])

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


def _hash_email(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=decrypt_field(user.email_encrypted),
        full_name=decrypt_field(user.full_name_encrypted),
        role=user.role,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
        last_login=user.last_login,
    )


@router.post("/register", response_model=RegisterResponse, status_code=201)
@limiter.limit("10/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    email_hash = _hash_email(body.email)

    existing = await db.execute(select(User).where(User.email_hash == email_hash))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="If this email is not already registered, an account has been created.",
        )

    invite = None
    workspace_id = None

    if body.invite_token:
        token_hash = _hash_token(body.invite_token)
        result = await db.execute(
            select(WorkspaceInvite).where(WorkspaceInvite.token_hash == token_hash)
        )
        invite = result.scalar_one_or_none()

        # Generic error — don't leak whether token exists or why it's invalid
        if not invite or invite.status != InviteStatus.PENDING:
            raise HTTPException(status_code=400, detail="Invalid or expired invite token.")
        if datetime.now(timezone.utc) > invite.expires_at:
            raise HTTPException(status_code=400, detail="Invalid or expired invite token.")
        if invite.invited_email_hash != email_hash:
            raise HTTPException(status_code=403, detail="This invite was sent to a different email address.")

        workspace_id = invite.workspace_id

    role = UserRole.COLLABORATOR if invite else UserRole.RESEARCHER

    user = User(
        email_encrypted=encrypt_field(body.email.lower()),
        full_name_encrypted=encrypt_field(body.full_name),
        email_hash=email_hash,
        hashed_password=hash_password(body.password),
        role=role,
    )
    db.add(user)
    await db.flush()

    if invite:
        member = WorkspaceMember(
            workspace_id=invite.workspace_id,
            user_id=user.id,
            role=MemberRole.COLLABORATOR,
            invited_by=invite.invited_by,
            joined_at=datetime.now(timezone.utc),
        )
        db.add(member)

        invite.status = InviteStatus.ACCEPTED
        invite.accepted_at = datetime.now(timezone.utc)

        await write_audit_log(
            db, AuditAction.INVITE_ACCEPTED,
            user_id=user.id,
            resource_type="workspace_invite",
            resource_id=invite.id,
            request=request,
        )

    await write_audit_log(
        db, AuditAction.REGISTER,
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        request=request,
    )

    return RegisterResponse(
        message="Registration successful.",
        user=_user_to_response(user),
        workspace_id=workspace_id,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    email_hash = _hash_email(body.email)
    result = await db.execute(select(User).where(User.email_hash == email_hash))
    user = result.scalar_one_or_none()

    auth_error = HTTPException(status_code=401, detail="Invalid email or password.")

    if not user:
        await write_audit_log(
            db, AuditAction.LOGIN_FAILED,
            status="failed", detail="Email not found", request=request,
        )
        raise auth_error

    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        await write_audit_log(
            db, AuditAction.LOGIN_FAILED, user_id=user.id,
            status="failed", detail="Account locked", request=request,
        )
        raise auth_error  # generic 401 — don't confirm the account exists

    if not verify_password(body.password, user.hashed_password):
        user.failed_login_attempts += 1

        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            await write_audit_log(
                db, AuditAction.ACCOUNT_LOCKED, user_id=user.id,
                detail=f"Locked after {MAX_FAILED_ATTEMPTS} failed attempts", request=request,
            )
        else:
            await write_audit_log(
                db, AuditAction.LOGIN_FAILED, user_id=user.id,
                status="failed",
                detail=f"Wrong password (attempt {user.failed_login_attempts})",
                request=request,
            )
        raise auth_error

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.now(timezone.utc)

    access_token = create_access_token(user.id, user.role.value)
    refresh_token = create_refresh_token(user.id)

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.APP_ENV == "production",
        samesite="lax",
        path="/api/auth/refresh",
    )

    await write_audit_log(db, AuditAction.LOGIN_SUCCESS, user_id=user.id, request=request)

    return TokenResponse(
        access_token=access_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing.")

    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    # Enforce absolute session lifetime — reject if session_iat + 7 days has passed
    session_iat_ts = payload.get("session_iat")
    if session_iat_ts is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")
    session_iat = datetime.fromtimestamp(session_iat_ts, tz=timezone.utc)
    if datetime.now(timezone.utc) > session_iat + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS):
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")

    new_access_token = create_access_token(user.id, user.role.value)
    new_refresh_token = create_refresh_token(user.id, session_iat=session_iat)
    await write_audit_log(db, AuditAction.TOKEN_REFRESHED, user_id=user.id, request=request)

    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=settings.APP_ENV == "production",
        samesite="lax",
        path="/api/auth/refresh",
    )
    return TokenResponse(
        access_token=new_access_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    response.delete_cookie("refresh_token", path="/api/auth/refresh")
    await write_audit_log(db, AuditAction.LOGOUT, user_id=current_user.id, request=request)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser):
    return _user_to_response(current_user)