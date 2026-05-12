"""
Tests for invite decline, workspace leave, and owner remove-member endpoints.

Execute sequence per route:
  decline_invite  : invite_by_token
  leave_workspace : workspace → member
  remove_member   : workspace → member

Run:
    cd backend
    pytest tests/test_member_management.py -v
"""
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.workspace_invite import InviteStatus
from app.models.workspace import MemberRole
from app.core.security import encrypt_field

from tests.conftest import USER_ID, OTHER_USER_ID, WORKSPACE_ID, _execute_result

# ── Fixed IDs ────────────────────────────────────────────────────────────────

MEMBER_ID    = "11111111-0000-0000-0000-000000000001"
INVITE_ID    = "ffffffff-0000-0000-0000-000000000006"
VALID_EMAIL  = "collab@hospital.org"
VALID_TOKEN  = "test_token_value"

DECLINE_URL     = "/api/invites/decline"
LEAVE_URL       = f"/api/workspaces/{WORKSPACE_ID}/members/me"
REMOVE_URL      = f"/api/workspaces/{WORKSPACE_ID}/members/{OTHER_USER_ID}"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _email_hash(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def make_user(user_id: str = USER_ID, email: str = VALID_EMAIL):
    u = MagicMock()
    u.id = user_id
    u.role = "researcher"
    u.is_active = True
    u.locked_until = None
    u.email_hash = _email_hash(email)
    return u


def make_workspace(owner_id: str = USER_ID):
    ws = MagicMock()
    ws.id = WORKSPACE_ID
    ws.owner_id = owner_id
    return ws


def make_member(user_id: str = USER_ID, role: MemberRole = MemberRole.COLLABORATOR):
    m = MagicMock()
    m.id = MEMBER_ID
    m.user_id = user_id
    m.workspace_id = WORKSPACE_ID
    m.role = role
    return m


def make_invite(status: InviteStatus = InviteStatus.PENDING, email: str = VALID_EMAIL, expired: bool = False):
    inv = MagicMock()
    inv.id = INVITE_ID
    inv.workspace_id = WORKSPACE_ID
    inv.invited_email_encrypted = encrypt_field(email)
    inv.invited_email_hash = _email_hash(email)
    inv.token_hash = hashlib.sha256(VALID_TOKEN.encode()).hexdigest()
    inv.status = status
    inv.invited_by = OTHER_USER_ID
    inv.expires_at = (
        datetime.now(timezone.utc) - timedelta(days=1)
        if expired
        else datetime.now(timezone.utc) + timedelta(days=7)
    )
    return inv


def make_db(*results):
    db = MagicMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    return db


@asynccontextmanager
async def client_as(user, db):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/invites/decline
# ═══════════════════════════════════════════════════════════════════════════

class TestDeclineInvite:

    async def test_unauthenticated_returns_403(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(DECLINE_URL, json={"token": VALID_TOKEN})
        assert resp.status_code == 403

    async def test_invalid_token_returns_400(self):
        db = make_db(_execute_result(scalar=None))
        async with client_as(make_user(), db) as ac:
            resp = await ac.post(DECLINE_URL, json={"token": "bad_token"})
        assert resp.status_code == 400

    async def test_already_accepted_returns_400(self):
        inv = make_invite(status=InviteStatus.ACCEPTED)
        db = make_db(_execute_result(scalar=inv))
        async with client_as(make_user(), db) as ac:
            resp = await ac.post(DECLINE_URL, json={"token": VALID_TOKEN})
        assert resp.status_code == 400

    async def test_expired_invite_returns_400(self):
        inv = make_invite(expired=True)
        db = make_db(_execute_result(scalar=inv))
        async with client_as(make_user(), db) as ac:
            resp = await ac.post(DECLINE_URL, json={"token": VALID_TOKEN})
        assert resp.status_code == 400

    async def test_wrong_email_returns_403(self):
        inv = make_invite(email="other@hospital.org")
        db = make_db(_execute_result(scalar=inv))
        async with client_as(make_user(email=VALID_EMAIL), db) as ac:
            resp = await ac.post(DECLINE_URL, json={"token": VALID_TOKEN})
        assert resp.status_code == 403

    async def test_valid_decline_returns_200_and_sets_declined(self):
        inv = make_invite()
        db = make_db(_execute_result(scalar=inv))
        async with client_as(make_user(), db) as ac:
            resp = await ac.post(DECLINE_URL, json={"token": VALID_TOKEN})
        assert resp.status_code == 200
        assert inv.status == InviteStatus.DECLINED


# ═══════════════════════════════════════════════════════════════════════════
# DELETE /api/workspaces/{id}/members/me
# ═══════════════════════════════════════════════════════════════════════════

class TestLeaveWorkspace:

    async def test_unauthenticated_returns_403(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.delete(LEAVE_URL)
        assert resp.status_code == 403

    async def test_workspace_not_found_returns_404(self):
        db = make_db(_execute_result(scalar=None))
        async with client_as(make_user(), db) as ac:
            resp = await ac.delete(LEAVE_URL)
        assert resp.status_code == 404

    async def test_not_a_member_returns_404(self):
        ws = make_workspace()
        db = make_db(_execute_result(scalar=ws), _execute_result(scalar=None))
        async with client_as(make_user(), db) as ac:
            resp = await ac.delete(LEAVE_URL)
        assert resp.status_code == 404

    async def test_owner_cannot_leave_returns_400(self):
        ws = make_workspace(owner_id=USER_ID)
        member = make_member(user_id=USER_ID, role=MemberRole.OWNER)
        db = make_db(_execute_result(scalar=ws), _execute_result(scalar=member))
        async with client_as(make_user(), db) as ac:
            resp = await ac.delete(LEAVE_URL)
        assert resp.status_code == 400

    async def test_collaborator_can_leave_returns_204(self):
        ws = make_workspace(owner_id=OTHER_USER_ID)
        member = make_member(user_id=USER_ID, role=MemberRole.COLLABORATOR)
        db = make_db(_execute_result(scalar=ws), _execute_result(scalar=member))
        async with client_as(make_user(), db) as ac:
            resp = await ac.delete(LEAVE_URL)
        assert resp.status_code == 204
        db.delete.assert_called_once_with(member)


# ═══════════════════════════════════════════════════════════════════════════
# DELETE /api/workspaces/{id}/members/{user_id}
# ═══════════════════════════════════════════════════════════════════════════

class TestRemoveMember:

    async def test_unauthenticated_returns_403(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.delete(REMOVE_URL)
        assert resp.status_code == 403

    async def test_non_owner_returns_403(self):
        ws = make_workspace(owner_id=OTHER_USER_ID)
        db = make_db(_execute_result(scalar=ws))
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.delete(REMOVE_URL)
        assert resp.status_code == 403

    async def test_owner_cannot_remove_themselves(self):
        ws = make_workspace(owner_id=USER_ID)
        db = make_db(_execute_result(scalar=ws))
        self_remove_url = f"/api/workspaces/{WORKSPACE_ID}/members/{USER_ID}"
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.delete(self_remove_url)
        assert resp.status_code == 400

    async def test_member_not_found_returns_404(self):
        ws = make_workspace(owner_id=USER_ID)
        db = make_db(_execute_result(scalar=ws), _execute_result(scalar=None))
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.delete(REMOVE_URL)
        assert resp.status_code == 404

    async def test_owner_removes_member_returns_204(self):
        ws = make_workspace(owner_id=USER_ID)
        member = make_member(user_id=OTHER_USER_ID, role=MemberRole.COLLABORATOR)
        db = make_db(_execute_result(scalar=ws), _execute_result(scalar=member))
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.delete(REMOVE_URL)
        assert resp.status_code == 204
        db.delete.assert_called_once_with(member)
