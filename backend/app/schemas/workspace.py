from pydantic import BaseModel, field_validator
from datetime import datetime
from app.models.workspace import MemberRole


class WorkspaceCreate(BaseModel):
    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Workspace name cannot be empty.")
        return v.strip()


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("Workspace name cannot be empty.")
        return v.strip() if v else v


class WorkspaceMemberResponse(BaseModel):
    id: str
    user_id: str
    role: MemberRole
    invited_by: str
    joined_at: datetime

    class Config:
        from_attributes = True


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
