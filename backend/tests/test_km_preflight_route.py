"""
Milestone 3 — KM preflight endpoint (route-level).

Covers workspace-member authorization, the no-store cache header, a ready
mapping returning counts, an unmapped mapping returning ready=false (HTTP
200, not an error), and that the audit detail carries no status cell values.
The counting/mapping logic itself is unit-tested in test_km_events.py.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import app
from app.api.dependencies import get_current_user
from app.core.database import get_db
import app.api.routes.analysis as analysis_route
from tests.conftest import _fake_user, make_member, make_dataset, WORKSPACE_ID, DATASET_ID, USER_ID

from httpx import AsyncClient, ASGITransport

PREFLIGHT_URL = f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}/analysis/km-preflight"

CSV = "dur,evt,arm\n2,relapse,A\n3,relapse,A\n4,censored,B\n5,relapse,B\n"


def _scalar_db(member, dataset):
    """AsyncSession mock for the analysis route (uses db.scalar, not execute)."""
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[member, dataset])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


async def _client(db):
    app.dependency_overrides[get_current_user] = lambda: _fake_user(USER_ID)
    app.dependency_overrides[get_db] = lambda: db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _patch_storage_and_audit(monkeypatch):
    # download returns the "encrypted" bytes; decrypt is identity for the test.
    monkeypatch.setattr(analysis_route.storage, "download_object", AsyncMock(return_value=CSV.encode()))
    monkeypatch.setattr(analysis_route, "decrypt_bytes", lambda b: b)
    captured = {}

    async def _fake_audit(db, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(analysis_route, "write_audit_log", _fake_audit)
    yield captured
    app.dependency_overrides.clear()


async def test_non_member_gets_403():
    db = _scalar_db(member=None, dataset=None)
    async with await _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "time_column": "dur", "event_column": "evt", "has_censoring": True,
            "event_mapping": [
                {"value": "relapse", "value_type": "string", "role": "event"},
                {"value": "censored", "value_type": "string", "role": "censored"},
            ],
        })
    assert r.status_code == 403


async def test_ready_mapping_returns_counts_and_no_store(_patch_storage_and_audit):
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with await _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "time_column": "dur", "event_column": "evt", "group_column": "arm",
            "has_censoring": True,
            "event_mapping": [
                {"value": "relapse", "value_type": "string", "role": "event"},
                {"value": "censored", "value_type": "string", "role": "censored"},
            ],
        })
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
    body = r.json()
    assert body["ready"] is True
    assert body["counts"]["used_rows"] == 4
    assert body["counts"]["events"] == 3
    assert body["counts"]["censored"] == 1
    assert body["counts"]["total_rows"] == body["counts"]["used_rows"] + body["counts"]["excluded_rows"]


async def test_unmapped_mapping_returns_ready_false_not_error():
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with await _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "time_column": "dur", "event_column": "evt", "has_censoring": True,
            # no mapping for the textual values -> unmapped, but still 200
        })
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert "unmapped_values" in body["blockers"]
    assert body["counts"]["unmapped_values"] == 2  # "relapse", "censored"


async def test_failed_preflight_is_audited_and_committed(_patch_storage_and_audit):
    # A validation failure still accessed and decrypted the dataset, so it must
    # be audited with status="failed" — and committed, because get_db rolls the
    # session back when the HTTPException propagates.
    captured = _patch_storage_and_audit
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with await _client(db) as ac:
        r = await ac.post(PREFLIGHT_URL, json={
            "time_column": "no_such_column", "event_column": "evt",
            "has_censoring": True, "event_mapping": [],
        })
    assert r.status_code == 422
    assert captured["action"].value == "analysis_preflighted"
    assert captured["status"] == "failed"
    db.commit.assert_awaited()


async def test_audit_detail_contains_no_status_values(_patch_storage_and_audit):
    captured = _patch_storage_and_audit
    db = _scalar_db(member=make_member(), dataset=make_dataset())
    async with await _client(db) as ac:
        await ac.post(PREFLIGHT_URL, json={
            "time_column": "dur", "event_column": "evt", "has_censoring": True,
            "event_mapping": [
                {"value": "relapse", "value_type": "string", "role": "event"},
                {"value": "censored", "value_type": "string", "role": "censored"},
            ],
        })
    assert captured["action"].value == "analysis_preflighted"
    detail = captured.get("detail", "")
    assert "relapse" not in detail and "censored" not in detail
