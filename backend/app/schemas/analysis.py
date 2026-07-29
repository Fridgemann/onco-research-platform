from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

from app.models.analysis_job import JobStatus, JobType


class AnalysisJobCreate(BaseModel):
    job_type: JobType
    parameters: Optional[dict[str, Any]] = None


# ── Kaplan-Meier preflight (Milestone 3) ────────────────────────────────────

KMValueType = Literal["boolean", "number", "string"]
KMMappingRole = Literal["event", "censored", "exclude"]

_KM_MAX_VALUE_STRING_LEN = 256


class KMEventMappingEntry(BaseModel):
    # bool is listed first so JSON true/false stays boolean (not coerced to 1/0).
    value: Union[bool, int, float, str, None] = None
    value_type: KMValueType
    role: KMMappingRole

    @field_validator("value")
    @classmethod
    def _bound_string_length(cls, v):
        if isinstance(v, str) and len(v) > _KM_MAX_VALUE_STRING_LEN:
            raise ValueError("event-mapping string value is too long")
        return v


class KMPreflightRequest(BaseModel):
    time_column: str = Field(max_length=256)
    event_column: Optional[str] = Field(default=None, max_length=256)
    group_column: Optional[str] = Field(default=None, max_length=256)
    has_censoring: bool = True
    event_mapping: list[KMEventMappingEntry] = Field(default_factory=list, max_length=200)
    all_events_confirmed: bool = False


class KMStatusValue(BaseModel):
    value: Union[bool, int, float, str, None] = None
    value_type: str
    count: int
    role: str


class KMPreflightResponse(BaseModel):
    ready: bool
    blockers: list[str]
    counts: dict[str, Any]
    status_values: list[KMStatusValue]


class AnalysisJobResponse(BaseModel):
    id: str
    dataset_id: str
    workspace_id: str
    requested_by: str
    job_type: str
    status: str
    parameters: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}
