"""
Milestone 4, Slice 2 — dataset inspect endpoint (route level).

Organised by OWASP Top 10:2025 category, matching test_dataset_security.py.

This endpoint returns real cell values to the browser, so it is the most
privacy-sensitive surface added so far. The rules it must uphold:
authorization on every request, an audit record for every inspection
(including failures, committed before the error propagates), no caching, no
cell values in logs/audits/errors/URLs, and server-side caps.

All fixtures here are synthetic.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.dependencies import get_current_user
from app.core.database import get_db
import app.api.routes.dataset as dataset_route
from app.schemas.dataset import INSPECT_MAX_PARSE_ROWS

from tests.conftest import (
    WORKSPACE_ID, OTHER_WS_ID, DATASET_ID, USER_ID,
    make_db, make_member, make_dataset, _execute_result, _fake_user,
)

INSPECT_URL = f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}/inspect"

# Synthetic cohort with a distinctive token that must never leak anywhere.
SECRET_TOKEN = "zzsecretvaluezz"
CSV = (
    "patient_id,months,status,arm\n"
    "1,6,relapse,A\n"
    "2,7,relapse,A\n"
    f"3,10,{SECRET_TOKEN},B\n"
    "4,,alive,B\n"
)


@pytest.fixture
def audited(monkeypatch):
    """Patch storage/decrypt and capture audit calls without touching a DB."""
    monkeypatch.setattr(
        dataset_route.storage, "download_object", AsyncMock(return_value=CSV.encode())
    )
    monkeypatch.setattr(dataset_route, "decrypt_bytes", lambda b: b)

    calls: list[dict] = []

    async def _fake_audit(db, *args, **kwargs):
        if args:
            kwargs.setdefault("action", args[0])
        calls.append(kwargs)

    monkeypatch.setattr(dataset_route, "write_audit_log", _fake_audit)
    yield calls
    app.dependency_overrides.clear()


def _client(db):
    app.dependency_overrides[get_current_user] = lambda: _fake_user(USER_ID)
    app.dependency_overrides[get_db] = lambda: db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ═══════════════════════════════════════════════════════════════════════════
# A01 — BROKEN ACCESS CONTROL
# ═══════════════════════════════════════════════════════════════════════════

class TestA01_AccessControl:

    async def test_unauthenticated_rejected(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get(INSPECT_URL)
        assert r.status_code == 403

    async def test_non_member_gets_403(self, audited):
        db = make_db(_execute_result(scalar=None))   # _require_member finds nothing
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)
        assert r.status_code == 403

    async def test_dataset_from_another_workspace_is_404(self, audited):
        # membership ok, but the dataset lookup is scoped by workspace_id
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=None))
        async with _client(db) as ac:
            r = await ac.get(
                f"/api/workspaces/{OTHER_WS_ID}/datasets/{DATASET_ID}/inspect"
            )
        assert r.status_code in (403, 404)

    async def test_missing_or_deleted_dataset_is_404(self, audited):
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=None))
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)
        assert r.status_code == 404

    async def test_member_can_inspect(self, audited):
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# A02 — CRYPTOGRAPHIC / TRANSPORT HYGIENE
# ═══════════════════════════════════════════════════════════════════════════

class TestA02_NoCaching:

    async def test_response_is_not_cacheable(self, audited):
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)
        assert r.headers.get("cache-control") == "no-store"


# ═══════════════════════════════════════════════════════════════════════════
# A04 — INSECURE DESIGN (caps and honest scope)
# ═══════════════════════════════════════════════════════════════════════════

class TestA04_CapsAndScope:

    async def test_small_file_reports_full_scope(self, audited):
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)
        profile = r.json()["profile"]
        assert profile["profile_scope"] == "full"
        assert profile["profiled_rows"] == 4
        assert profile["total_rows"] == 4

    async def test_file_over_parse_cap_reports_partial_and_unknown_total(self, monkeypatch, audited):
        big = "a\n" + "\n".join(str(i) for i in range(INSPECT_MAX_PARSE_ROWS + 500)) + "\n"
        monkeypatch.setattr(
            dataset_route.storage, "download_object", AsyncMock(return_value=big.encode())
        )
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)
        profile = r.json()["profile"]
        assert profile["profile_scope"] == "partial"
        assert profile["profiled_rows"] == INSPECT_MAX_PARSE_ROWS
        assert profile["total_rows"] is None

    async def test_columns_and_samples_are_capped(self, audited):
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)
        body = r.json()
        assert body["columns_returned"] == len(body["columns"])
        assert len(body["sample_rows"]) <= 20


# ═══════════════════════════════════════════════════════════════════════════
# A03/A09 — NO CELL VALUES IN ERRORS, LOGS, AUDITS
# ═══════════════════════════════════════════════════════════════════════════

class TestA03_SanitizedFailures:

    async def test_unparseable_dataset_returns_sanitized_422(self, monkeypatch, audited):
        monkeypatch.setattr(
            dataset_route.storage,
            "download_object",
            AsyncMock(return_value=b"\xff\xfe\x00binary-not-csv"),
        )
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)
        assert r.status_code == 422
        assert "binary-not-csv" not in r.text


    async def test_overlong_column_name_rejected_sanitized_and_audited(self, monkeypatch, audited):
        # A huge header amplifies: the name repeats as a JSON key in every
        # sample row, so it is rejected before any rows are built.
        huge = "h" * 300
        monkeypatch.setattr(
            dataset_route.storage,
            "download_object",
            AsyncMock(return_value=f"{huge},ok\n1,2\n".encode()),
        )
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)

        assert r.status_code == 422
        assert huge not in r.text          # identifier never echoed back
        assert "256" in r.text             # the limit is stated
        assert len(audited) == 1
        assert audited[0]["status"] == "failed"
        db.commit.assert_awaited()


class TestA09_AuditLogging:

    async def test_successful_inspection_is_audited(self, audited):
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            await ac.get(INSPECT_URL)
        assert len(audited) == 1
        assert audited[0]["action"].value == "dataset_inspected"
        assert audited[0]["status"] == "success"
        assert audited[0]["resource_id"] == DATASET_ID

    async def test_failed_inspection_is_audited_and_committed(self, monkeypatch, audited):
        # A failure still decrypted and read the dataset — it must be recorded,
        # and committed, because get_db rolls back when the error propagates.
        monkeypatch.setattr(
            dataset_route.storage, "download_object", AsyncMock(return_value=b"\xff\xfe\x00bad")
        )
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)
        assert r.status_code == 422
        assert len(audited) == 1
        assert audited[0]["status"] == "failed"
        db.commit.assert_awaited()

    async def test_storage_failure_is_audited_and_sanitized(self, monkeypatch, audited):
        # Regression: the download used to sit outside the guarded block, so a
        # MinIO/network failure produced neither a failed audit nor a safe error.
        monkeypatch.setattr(
            dataset_route.storage,
            "download_object",
            AsyncMock(side_effect=OSError(f"minio unreachable {SECRET_TOKEN}")),
        )
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)

        # upstream failure, not "your data is malformed"
        assert r.status_code == 503
        assert SECRET_TOKEN not in r.text
        assert len(audited) == 1
        assert audited[0]["status"] == "failed"
        db.commit.assert_awaited()


    async def test_audit_detail_contains_no_cell_values(self, audited):
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            await ac.get(INSPECT_URL)
        detail = audited[0].get("detail") or ""
        assert SECRET_TOKEN not in detail
        for token in ("relapse", "alive"):
            assert token not in detail

    async def test_cell_values_never_appear_in_the_url(self, audited):
        # The endpoint takes ids in the path only; nothing data-derived.
        db = make_db(_execute_result(scalar=make_member()), _execute_result(scalar=make_dataset()))
        async with _client(db) as ac:
            r = await ac.get(INSPECT_URL)
        assert SECRET_TOKEN not in str(r.url)
        # ...but the authorised member does receive the values in the body
        assert SECRET_TOKEN in r.text
