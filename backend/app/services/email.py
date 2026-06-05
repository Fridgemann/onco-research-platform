import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_invite_email(to_email: str, plain_token: str, workspace_name: str) -> None:
    invite_url = f"{settings.FRONTEND_URL}/invites/accept?token={plain_token}"

    if settings.APP_ENV != "production":
        logger.info(
            "DEV invite email — to=%s workspace=%r link=%s",
            to_email, workspace_name, invite_url,
        )
        return

    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.error("SMTP credentials not configured — invite email not sent to %s", to_email)
        return

    try:
        await asyncio.to_thread(_send_smtp, to_email, workspace_name, invite_url)
    except Exception:
        logger.exception("Failed to send invite email to %s", to_email)


async def send_researcher_invite_email(to_email: str, plain_token: str) -> None:
    invite_url = f"{settings.FRONTEND_URL}/register?researcher_invite={plain_token}"

    if settings.APP_ENV != "production":
        logger.info("DEV researcher invite email — to=%s link=%s", to_email, invite_url)
        return

    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.error("SMTP credentials not configured — researcher invite not sent to %s", to_email)
        return

    try:
        await asyncio.to_thread(_send_researcher_smtp, to_email, invite_url)
    except Exception:
        logger.exception("Failed to send researcher invite email to %s", to_email)


def _send_researcher_smtp(to_email: str, invite_url: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "You've been invited to join OncoResearch as a Researcher"
    msg["From"] = settings.EMAILS_FROM
    msg["To"] = to_email

    text = (
        "You've been invited to join the OncoResearch platform as a researcher.\n\n"
        f"Create your account: {invite_url}\n\n"
        "This link expires in 7 days."
    )
    html = (
        "<p>You've been invited to join the <strong>OncoResearch</strong> platform as a researcher.</p>"
        f'<p><a href="{invite_url}">Create your researcher account</a></p>'
        "<p>This link expires in 7 days.</p>"
    )

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.sendmail(settings.EMAILS_FROM, to_email, msg.as_string())


def _send_smtp(to_email: str, workspace_name: str, invite_url: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"You've been invited to join {workspace_name}"
    msg["From"] = settings.EMAILS_FROM
    msg["To"] = to_email

    text = (
        f"You've been invited to collaborate on {workspace_name}.\n\n"
        f"Accept your invitation: {invite_url}\n\n"
        "This link expires in 7 days."
    )
    html = (
        f"<p>You've been invited to collaborate on <strong>{workspace_name}</strong>.</p>"
        f'<p><a href="{invite_url}">Accept Invitation</a></p>'
        "<p>This link expires in 7 days.</p>"
    )

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.sendmail(settings.EMAILS_FROM, to_email, msg.as_string())
