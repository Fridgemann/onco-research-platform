from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request
from app.models.audit_log import AuditLog, AuditAction
import logging

logger = logging.getLogger("audit")


async def write_audit_log(
    db: AsyncSession,
    action: AuditAction,
    *,
    user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    status: str = "success",
    detail: str | None = None,
    request: Request | None = None,
) -> None:
    ip_address = None
    user_agent = None

    if request:
        forwarded = request.headers.get("X-Forwarded-For")
        ip_address = forwarded.split(",")[0].strip() if forwarded else request.client.host
        user_agent = request.headers.get("User-Agent", "")[:256]

    log_entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        status=status,
        detail=detail,
    )

    db.add(log_entry)
    await db.flush()

    logger.info(
        "AUDIT",
        extra={
            "user_id": user_id,
            "action": action.value,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "ip": ip_address,
            "status": status,
            "detail": detail,
        },
    )