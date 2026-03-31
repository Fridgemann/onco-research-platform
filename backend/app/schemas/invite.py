from pydantic import BaseModel, EmailStr
from datetime import datetime
from app.models.workspace_invite import InviteStatus


class InviteCreateRequest(BaseModel):
    email: EmailStr


class InviteCreateResponse(BaseModel):
    invite_id: str
    token: str
    expires_at: datetime
    message: str


class InviteResponse(BaseModel):
    id: str
    workspace_id: str
    invited_email: str
    status: InviteStatus
    invited_by: str
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None


class InviteAcceptRequest(BaseModel):
    token: str


class InviteAcceptResponse(BaseModel):
    message: str
    workspace_id: str
    role: str
