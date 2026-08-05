"""
Milestone 4, Slice 3 — non-KM preflight endpoint (route level).

Mirrors the km-preflight route's security posture: workspace-member
authorization, dataset access audited on success and failure, no caching,
and sanitized errors. All fixtures are synthetic.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.dependencies import get_current_user
from app.core.database import get_db
import app.api.routes.analysis as analysis_route
from tests.conftest import WORKSPACE_ID, DATASET_ID, USER_ID, _fake_user, make_member, make_dataset

PREFLIGHT_URL = f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}/analysis/preflight"

SECRET_TOKEN = "zzsecretoutcomezz"
CSV = (
    "x,y,label\n"
    "1,0,alive\n"
    "2,0,alive\n"
    "3,1,dead\n"
    "4,1,dead\n"
    f"5,,{SECRET_TOKEN}\n"
)


def _scalar_db(member, dataset):
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[member, dataset])

    # SQLAlchemy column defaults (id, status, created_at) only fire on a real
    # flush/INSERT, so populate them on add() the way conftest does for
    # Dataset — otherwise the response model has nothing to serialize.
    def _add_with_defaults(obj):
        from datetime import datetime, timezone
        import uuid as _uuid
        from app.models.analysis_job import JobStatus

        if getattr(obj, "id", None) is None:
            obj.id = str(_uuid.uuid4())
        if getattr(obj, "status", None) is None:
            obj.status = JobStatus.PENDING
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    db.add = MagicMock(side_effect=_add_with_defaults)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _client(db):
    app.dependency_overrides[get_current_user] = lambda: _fake_user(USER_ID)
    app.dependency_overrides[get_db] = lambda: db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def audited(monkeypatch):
    monkeypatch.setattr(
        analysis_route.storage, "download_object", AsyncMock(return_value=CSV.encode())
    )
    monkeypatch.setattr(analysis_route, "decrypt_bytes", lambda b: b)

    calls: list[dict] = []

    async def _fake_audit(db, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(analysis_route, "write_audit_log", _fake_audit)
    yield calls
    app.dependency_overrides.clear()


async def test_non_member_gets_403(audited):
    db = _scalar_db(member=None, dataset=None)
    async with _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "job_type": "regression",
            "parameters": {"target_column": "y", "feature_columns": ["x"]},
        })
    assert r.status_code == 403


async def test_regression_preflight_returns_counts_and_no_store(audited):
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "job_type": "regression",
            "parameters": {"target_column": "y", "feature_columns": ["x"]},
        })
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
    body = r.json()
    assert body["ready"] is True
    assert body["counts"]["used_rows"] == 4        # the blank y row is excluded
    assert body["counts_by_column"] is None


async def test_descriptive_preflight_returns_per_column_counts(audited):
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "job_type": "descriptive_stats",
            "parameters": {"columns": ["x", "y"]},
        })
    body = r.json()
    assert r.status_code == 200
    assert body["counts"] is None                   # joint counts would mislead
    assert body["counts_by_column"]["y"]["used_rows"] == 4


async def test_logistic_preflight_is_not_ready_until_outcome_chosen(audited):
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "job_type": "logistic_regression",
            "parameters": {"target_column": "y", "feature_columns": ["x"]},
        })
    body = r.json()
    assert body["ready"] is False
    assert "positive_class_unconfirmed" in body["blockers"]
    assert len(body["target_classes"]) == 2
    assert body["suggested_positive_class"] == {"value": 1.0, "value_type": "number"}


async def test_logistic_preflight_ready_once_outcome_confirmed(audited):
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "job_type": "logistic_regression",
            "parameters": {
                "target_column": "y", "feature_columns": ["x"],
                "positive_class": {"value": 1, "value_type": "number"},
            },
        })
    body = r.json()
    assert body["ready"] is True
    assert body["positive_class"] == {"value": 1.0, "value_type": "number"}


async def test_kaplan_meier_directed_to_its_own_endpoint(audited):
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "job_type": "kaplan_meier",
            "parameters": {"time_column": "x", "event_column": "y"},
        })
    assert r.status_code == 422
    assert "Kaplan" in r.json()["detail"]


async def test_failed_preflight_is_audited_and_committed(audited):
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "job_type": "regression",
            "parameters": {"target_column": "no_such_column", "feature_columns": ["x"]},
        })
    assert r.status_code == 422
    assert audited[-1]["status"] == "failed"
    db.commit.assert_awaited()


async def test_audit_detail_names_the_generic_preflight_and_leaks_nothing(audited):
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with _client(db) as ac:
        await ac.post(PREFLIGHT_URL, json={
            "job_type": "regression",
            "parameters": {"target_column": "y", "feature_columns": ["x"]},
        })
    detail = audited[-1]["detail"]
    assert "analysis_preflight" in detail       # not mislabelled as km_preflight
    assert SECRET_TOKEN not in detail
    assert audited[-1]["status"] == "success"


async def test_storage_failure_is_audited_and_sanitized(monkeypatch, audited):
    monkeypatch.setattr(
        analysis_route.storage,
        "download_object",
        AsyncMock(side_effect=OSError(f"minio down {SECRET_TOKEN}")),
    )
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "job_type": "regression",
            "parameters": {"target_column": "y", "feature_columns": ["x"]},
        })
    assert r.status_code == 503
    assert SECRET_TOKEN not in r.text
    assert audited[-1]["status"] == "failed"


SUBMIT_URL = f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}/analysis"


class TestOutcomeSelectionIsEnforcedAtTheBoundary:
    """The worker keeps a compatibility fallback for legacy/direct calls, so
    the requirement that an outcome is chosen has to be enforced where new
    jobs are actually created — otherwise a client can simply omit it."""

    async def test_logistic_submission_without_outcome_is_rejected(self, audited, monkeypatch):
        monkeypatch.setattr(analysis_route.run_analysis_task, "delay", MagicMock())
        db = _scalar_db(make_member(), make_dataset())
        async with _client(db) as ac:
            r = await ac.post(SUBMIT_URL, json={
                "job_type": "logistic_regression",
                "parameters": {"target_column": "y", "feature_columns": ["x"]},
            })
        assert r.status_code == 422
        assert "outcome" in r.text.lower()
        analysis_route.run_analysis_task.delay.assert_not_called()

    async def test_logistic_submission_with_malformed_outcome_is_rejected(self, audited, monkeypatch):
        monkeypatch.setattr(analysis_route.run_analysis_task, "delay", MagicMock())
        db = _scalar_db(make_member(), make_dataset())
        async with _client(db) as ac:
            r = await ac.post(SUBMIT_URL, json={
                "job_type": "logistic_regression",
                "parameters": {"target_column": "y", "feature_columns": ["x"],
                               "positive_class": {"value": 1}},   # no value_type
            })
        assert r.status_code == 422

    async def test_logistic_submission_with_outcome_is_accepted(self, audited, monkeypatch):
        monkeypatch.setattr(analysis_route.run_analysis_task, "delay", MagicMock())
        db = _scalar_db(make_member(), make_dataset())
        async with _client(db) as ac:
            r = await ac.post(SUBMIT_URL, json={
                "job_type": "logistic_regression",
                "parameters": {"target_column": "y", "feature_columns": ["x"],
                               "positive_class": {"value": 1, "value_type": "number"}},
            })
        assert r.status_code == 202

    async def test_other_analyses_are_unaffected(self, audited, monkeypatch):
        monkeypatch.setattr(analysis_route.run_analysis_task, "delay", MagicMock())
        db = _scalar_db(make_member(), make_dataset())
        async with _client(db) as ac:
            r = await ac.post(SUBMIT_URL, json={
                "job_type": "regression",
                "parameters": {"target_column": "y", "feature_columns": ["x"]},
            })
        assert r.status_code == 202


class TestAuditLabelling:

    async def test_validation_failure_is_labelled_analysis_preflight(self, audited):
        # A rejected generic preflight must not be recorded as a KM preflight.
        db = _scalar_db(make_member(), make_dataset())
        async with _client(db) as ac:
            r = await ac.post(PREFLIGHT_URL, json={
                "job_type": "kaplan_meier",          # rejected by the dispatcher
                "parameters": {"time_column": "x", "event_column": "y"},
            })
        assert r.status_code == 422
        assert len(audited) == 1
        assert audited[0]["status"] == "failed"
        assert "analysis_preflight" in audited[0]["detail"]
        assert "km_preflight" not in audited[0]["detail"]
