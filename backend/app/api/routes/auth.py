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
        raise HTTPException(status_code=409, detail="Email already registered.")

    user = User(
        email_encrypted=encrypt_field(body.email.lower()),
        full_name_encrypted=encrypt_field(body.full_name),
        email_hash=email_hash,
        hashed_password=hash_password(body.password),
        role=UserRole.RESEARCHER,
    )
    db.add(user)
    await db.flush()

    await write_audit_log(
        db, AuditAction.REGISTER,
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        request=request,
    )

    return RegisterResponse(message="Registration successful.", user=_user_to_response(user))


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
        raise HTTPException(
            status_code=403,
            detail=f"Account locked. Try again after {user.locked_until.isoformat()}.",
        )

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
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
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
    db: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing.")

    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")

    new_access_token = create_access_token(user.id, user.role.value)
    await write_audit_log(db, AuditAction.TOKEN_REFRESHED, user_id=user.id, request=request)

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