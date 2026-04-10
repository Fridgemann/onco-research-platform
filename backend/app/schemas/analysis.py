from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.models.analysis_job import JobStatus, JobType


class AnalysisJobCreate(BaseModel):
    job_type: JobType
    parameters: Optional[dict[str, Any]] = None


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
