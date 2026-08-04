"""
Shared fixtures for dataset security tests.

DB mock pattern:
  - db.execute() is AsyncMock — configure side_effect per test
  - db.add() / db.flush() are no-ops
  - Route order: _require_member execute → (optional) dataset execute → audit add+flush
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token
from app.models.workspace import MemberRole

# ── Fixed IDs used across all tests ────────────────────────────────────────
USER_ID       = "aaaaaaaa-0000-0000-0000-000000000001"
OTHER_USER_ID = "bbbbbbbb-0000-0000-0000-000000000002"
WORKSPACE_ID  = "cccccccc-0000-0000-0000-000000000003"
OTHER_WS_ID   = "dddddddd-0000-0000-0000-000000000004"
DATASET_ID    = "eeeeeeee-0000-0000-0000-000000000005"

# ── Token helpers ───────────────────────────────────────────────────────────

@pytest.fixture
def access_token():
    return create_access_token(USER_ID, "researcher")

@pytest.fixture
def other_access_token():
    return create_access_token(OTHER_USER_ID, "researcher")

@pytest.fixture
def refresh_token_str():
    return create_refresh_token(USER_ID)

# ── Fake user injected via dependency override ──────────────────────────────

def _fake_user(user_id: str = USER_ID):
    u = MagicMock()
    u.id = user_id
    u.role = "researcher"
    u.is_active = True
    u.locked_until = None
    return u

# ── DB mock builder ─────────────────────────────────────────────────────────

def _execute_result(scalar=None, scalars_list=None):
    """Wraps a return value in a result mock matching SQLAlchemy's API."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.scalars.return_value.all.return_value = scalars_list if scalars_list is not None else []
    return r

def make_db(first_result, second_result=None):
    """
    Build a mock AsyncSession.

    first_result  — what _require_member's execute() returns (a scalar: member or None)
    second_result — what the dataset query's execute() returns (a scalar or list)
    """
    from app.models.dataset import Dataset

    db = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    # Routes that audit on a failure path commit explicitly, because get_db
    # rolls back when the error propagates. Awaitable so those paths work.
    db.commit = AsyncMock()

    # SQLAlchemy column defaults (created_at, updated_at) only fire during a
    # real flush/INSERT.  Simulate that by setting them when add() is called.
    def _add_with_defaults(obj):
        if isinstance(obj, Dataset):
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
            if obj.updated_at is None:
                obj.updated_at = datetime.now(timezone.utc)

    db.add = MagicMock(side_effect=_add_with_defaults)

    if second_result is not None:
        db.execute.side_effect = [first_result, second_result]
    else:
        db.execute.return_value = first_result

    return db

# ── Kaplan-Meier result helpers (collision-safe groups list) ────────────────

def km_curve(result, label):
    """Return the curve dict for a group label from a KM result's groups list."""
    for g in result["groups"]:
        if str(g["label"]) == str(label):
            return g["curve"]
    raise KeyError(f"group label {label!r} not found in {[g['label'] for g in result['groups']]}")


def km_overall(result):
    """Return the single curve for a non-grouped KM result."""
    return result["groups"][0]["curve"]


def km_labels(result):
    """Return the set of (label, value_type) pairs from a KM result."""
    return {(g["label"], g["value_type"]) for g in result["groups"]}


def make_member(role: MemberRole = MemberRole.OWNER, user_id: str = USER_ID):
    m = MagicMock()
    m.user_id = user_id
    m.workspace_id = WORKSPACE_ID
    m.role = role
    return m

def make_dataset(uploaded_by: str = USER_ID, workspace_id: str = WORKSPACE_ID):
    from app.core.security import encrypt_field
    d = MagicMock()
    d.id = DATASET_ID
    d.workspace_id = workspace_id
    d.uploaded_by = uploaded_by
    d.filename_encrypted = encrypt_field("patients.csv")
    d.content_type = "text/csv"
    d.file_size = 128
    d.description = None
    d.object_key = f"{workspace_id}/{DATASET_ID}"
    d.created_at = datetime.now(timezone.utc)
    d.is_deleted = False
    return d

# ── Client fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    """Unauthenticated async client — used for auth failure tests."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

@pytest.fixture
def upload_url():
    return f"/api/workspaces/{WORKSPACE_ID}/datasets"

@pytest.fixture
def dataset_url():
    return f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}"

# ── Context manager that overrides both auth + db ───────────────────────────

from contextlib import asynccontextmanager

@asynccontextmanager
async def authed_client(db, user_id: str = USER_ID):
    """
    Yields an AsyncClient with get_current_user and get_db both overridden.
    Cleans up dependency_overrides after use.
    """
    fake = _fake_user(user_id)
    app.dependency_overrides[get_current_user] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)
