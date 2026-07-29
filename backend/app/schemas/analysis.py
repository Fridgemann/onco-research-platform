from datetime import datetime
from typing import Any, Optional, Union

from pydantic import BaseModel, Field

from app.models.analysis_job import JobStatus, JobType


class AnalysisJobCreate(BaseModel):
    job_type: JobType
    parameters: Optional[dict[str, Any]] = None


# ── Kaplan-Meier preflight (Milestone 3) ────────────────────────────────────

class KMEventMappingEntry(BaseModel):
    # bool is listed first so JSON true/false stays boolean (not coerced to 1/0).
    value: Union[bool, int, float, str, None] = None
    value_type: str
    role: str


class KMPreflightRequest(BaseModel):
    time_column: str
    event_column: Optional[str] = None
    group_column: Optional[str] = None
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
