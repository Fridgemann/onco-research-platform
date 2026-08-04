from datetime import datetime
from typing import Any, Optional, Union

from pydantic import BaseModel

ALLOWED_EXTENSIONS = {".csv", ".tsv", ".json", ".xlsx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# ── Dataset inspection caps (Milestone 4) ───────────────────────────────────
#
# The inspect endpoint returns real cell values, so every dimension of the
# response is bounded server-side: how many rows are shown, how many columns
# are described, how many distinct values are listed, how long any single
# string may be, and how much of the file is parsed at all.
INSPECT_MAX_SAMPLE_ROWS = 20
INSPECT_MAX_COLUMNS = 200
INSPECT_MAX_DISTINCT = 20
INSPECT_MAX_STRING_LEN = 64
INSPECT_MAX_PARSE_ROWS = 50_000

# Column names are identifiers the caller sends back to select analysis
# roles, so they are never truncated — an overlong one is rejected instead.
# Bounding the column COUNT alone does not bound the response: every name is
# repeated as a JSON key in every sample row, so one huge header would
# amplify into a far larger response than the row cap suggests.
INSPECT_MAX_COLUMN_NAME_LEN = 256

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


# ── Dataset inspection response ─────────────────────────────────────────────

class DatasetProfileScope(BaseModel):
    """How much of the file the figures below actually describe.

    `total_rows` is null when the file exceeded the parse cap: the true row
    count is unknown at that point and is deliberately not estimated, so a
    sampled figure can never be mistaken for a whole-cohort figure.
    """
    profiled_rows: int
    profile_scope: str          # "full" | "partial"
    total_rows: Optional[int] = None


class DatasetTypedValue(BaseModel):
    """A distinct cell value, keeping its original JSON type (1 is not "1")."""
    value: Union[bool, int, float, str, None] = None
    value_type: str


class DatasetColumnProfile(BaseModel):
    name: str
    display_type: str           # numeric | categorical | binary | empty
    missing: int                # counts below are over profiled_rows
    missing_percent: float
    non_numeric: int
    distinct_count: Optional[int] = None       # null when above the cap
    distinct_values: Optional[list[DatasetTypedValue]] = None
    example_values: list[Any] = []


class DatasetInspectResponse(BaseModel):
    profile: DatasetProfileScope
    column_count: int           # true width of the file
    columns_returned: int       # how many are described below
    columns_truncated: bool
    sample_rows: list[dict[str, Any]]
    columns: list[DatasetColumnProfile]
