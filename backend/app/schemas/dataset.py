from datetime import datetime

from pydantic import BaseModel

ALLOWED_EXTENSIONS = {".csv", ".tsv", ".json", ".xlsx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

ALLOWED_CONTENT_TYPES: dict[str, set[str]] = {
    ".csv": {"text/csv", "application/vnd.ms-excel", "application/csv", "text/plain"},
    ".tsv": {"text/tab-separated-values", "text/plain"},
    ".json": {"application/json", "text/plain"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}


class DatasetResponse(BaseModel):
    id: str
    workspace_id: str
    filename: str
    content_type: str
    file_size: int
    description: str | None
    uploaded_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class DatasetDeleteResponse(BaseModel):
    message: str
