"""
Invite endpoint security and functional tests.

Organised by OWASP Top 10:2025 so findings map to a security report.

Execute sequence per route (order matters for side_effect):
  create_invite  : workspace → existing_member → existing_invite
  list_invites   : workspace → invites_list
  revoke_invite  : workspace → invite
  accept_invite  : invite_by_token → existing_member

Run:
    cd backend
    pytest tests/test_invite.py -v --asyncio-mode=auto
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
from app.models.user import UserRole
from app.core.security import encrypt_field

from tests.conftest import (
    USER_ID, OTHER_USER_ID, WORKSPACE_ID,
    _execute_result,
)

# ── Fixed IDs ───────────────────────────────────────────────────────────────

INVITE_ID    = "ffffffff-0000-0000-0000-000000000006"
VALID_EMAIL  = "collab@hospital.org"
VALID_TOKEN  = "test_token_value"

INVITE_URL  = f"/api/workspaces/{WORKSPACE_ID}/invites"
REVOKE_URL  = f"/api/workspaces/{WORKSPACE_ID}/invites/{INVITE_ID}"
ACCEPT_URL  = "/api/invites/accept"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _email_hash(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def make_workspace(owner_id: str = USER_ID):
    ws = MagicMock()
    ws.id = WORKSPACE_ID
    ws.owner_id = owner_id
    return ws


def make_invite(status: str = "pending", email: str = VALID_EMAIL, expired: bool = False):
    inv = MagicMock()
    inv.id = INVITE_ID
    inv.workspace_id = WORKSPACE_ID
    inv.invited_email_encrypted = encrypt_field(email)
    inv.invited_email_hash = _email_hash(email)
    inv.token_hash = hashlib.sha256(VALID_TOKEN.encode()).hexdigest()
    inv.status = InviteStatus(status)
    inv.invited_by = USER_ID
    inv.created_at = datetime.now(timezone.utc)
    inv.expires_at = (
        datetime.now(timezone.utc) - timedelta(days=1)
        if expired
        else datetime.now(timezone.utc) + timedelta(days=7)
    )
    inv.accepted_at = None
    return inv


def make_db_multi(*results):
    """AsyncSession mock with n execute() return values consumed in order."""
    import uuid as _uuid
    from app.models.workspace_invite import WorkspaceInvite

    def _add_with_defaults(obj):
        if isinstance(obj, WorkspaceInvite) and obj.id is None:
            obj.id = str(_uuid.uuid4())

    db = MagicMock()
    db.flush = AsyncMock()
    db.add = MagicMock(side_effect=_add_with_defaults)
    db.execute = AsyncMock(side_effect=list(results))
    return db


@asynccontextmanager
async def client_as(user, db):
    """Override auth + DB for a specific user object."""
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)


def make_user(user_id: str = USER_ID, email: str = VALID_EMAIL):
    u = MagicMock()
    u.id = user_id
    u.role = "researcher"
    u.is_active = True
    u.locked_until = None
    u.email_hash = _email_hash(email)
    return u


# ═══════════════════════════════════════════════════════════════════════════
# A01 — BROKEN ACCESS CONTROL: authentication checks
# ═══════════════════════════════════════════════════════════════════════════

class TestA01_Authentication:

    async def test_create_invite_unauthenticated(self):
        """No Bearer token → 403 before any DB touch."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(INVITE_URL, json={"email": VALID_EMAIL})
        assert resp.status_code == 403

    async def test_list_invites_unauthenticated(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(INVITE_URL)
        assert resp.status_code == 403

    async def test_revoke_invite_unauthenticated(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.delete(REVOKE_URL)
        assert resp.status_code == 403

    async def test_accept_invite_unauthenticated(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(ACCEPT_URL, json={"token": VALID_TOKEN})
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# A01 — BROKEN ACCESS CONTROL: ownership enforcement
# ═══════════════════════════════════════════════════════════════════════════

class TestA01_Ownership:

    async def test_non_owner_cannot_create_invite(self):
        """Collaborator (not owner) gets 403."""
        db = make_db_multi(
            _execute_result(scalar=make_workspace(owner_id=OTHER_USER_ID)),
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.post(INVITE_URL, json={"email": VALID_EMAIL})
        assert resp.status_code == 403

    async def test_non_owner_cannot_list_invites(self):
        db = make_db_multi(
            _execute_result(scalar=make_workspace(owner_id=OTHER_USER_ID)),
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.get(INVITE_URL)
        assert resp.status_code == 403

    async def test_non_owner_cannot_revoke_invite(self):
        db = make_db_multi(
            _execute_result(scalar=make_workspace(owner_id=OTHER_USER_ID)),
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.delete(REVOKE_URL)
        assert resp.status_code == 403

    async def test_wrong_email_cannot_accept_invite(self):
        """Token is valid but belongs to a different email — 403, not 400."""
        db = make_db_multi(
            _execute_result(scalar=make_invite(email=VALID_EMAIL)),
        )
        async with client_as(make_user(USER_ID, email="attacker@evil.com"), db) as ac:
            resp = await ac.post(ACCEPT_URL, json={"token": VALID_TOKEN})
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# CREATE INVITE — functional
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateInvite:

    async def test_owner_creates_invite_returns_token(self):
        db = make_db_multi(
            _execute_result(scalar=make_workspace()),  # workspace
            _execute_result(scalar=None),               # not already a member
            _execute_result(scalar=None),               # no pending invite
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.post(INVITE_URL, json={"email": VALID_EMAIL})
        assert resp.status_code == 201
        body = resp.json()
        assert "token" in body
        assert "invite_id" in body
        assert "expires_at" in body

    async def test_workspace_not_found(self):
        db = make_db_multi(_execute_result(scalar=None))
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.post(INVITE_URL, json={"email": VALID_EMAIL})
        assert resp.status_code == 404

    async def test_already_member_conflict(self):
        db = make_db_multi(
            _execute_result(scalar=make_workspace()),
            _execute_result(scalar=MagicMock()),  # existing member
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.post(INVITE_URL, json={"email": VALID_EMAIL})
        assert resp.status_code == 409
        assert "already a member" in resp.json()["detail"]

    async def test_pending_invite_already_exists(self):
        db = make_db_multi(
            _execute_result(scalar=make_workspace()),
            _execute_result(scalar=None),               # not a member
            _execute_result(scalar=make_invite()),       # pending invite exists
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.post(INVITE_URL, json={"email": VALID_EMAIL})
        assert resp.status_code == 409
        assert "pending invite" in resp.json()["detail"]

    async def test_invalid_email_format_rejected(self):
        """Pydantic EmailStr validation — no DB touch needed."""
        db = make_db_multi()
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.post(INVITE_URL, json={"email": "not-an-email"})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# LIST INVITES — functional
# ═══════════════════════════════════════════════════════════════════════════

class TestListInvites:

    async def test_owner_sees_all_invites(self):
        invites = [make_invite(), make_invite(status="accepted")]
        db = make_db_multi(
            _execute_result(scalar=make_workspace()),
            _execute_result(scalars_list=invites),
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.get(INVITE_URL)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_empty_workspace_returns_empty_list(self):
        db = make_db_multi(
            _execute_result(scalar=make_workspace()),
            _execute_result(scalars_list=[]),
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.get(INVITE_URL)
        assert resp.status_code == 200
        assert resp.json() == []


# ═══════════════════════════════════════════════════════════════════════════
# REVOKE INVITE — functional
# ═══════════════════════════════════════════════════════════════════════════

class TestRevokeInvite:

    async def test_owner_revokes_pending_invite(self):
        db = make_db_multi(
            _execute_result(scalar=make_workspace()),
            _execute_result(scalar=make_invite()),
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.delete(REVOKE_URL)
        assert resp.status_code == 204

    async def test_invite_not_found(self):
        db = make_db_multi(
            _execute_result(scalar=make_workspace()),
            _execute_result(scalar=None),
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.delete(REVOKE_URL)
        assert resp.status_code == 404

    async def test_cannot_revoke_already_accepted(self):
        db = make_db_multi(
            _execute_result(scalar=make_workspace()),
            _execute_result(scalar=make_invite(status="accepted")),
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.delete(REVOKE_URL)
        assert resp.status_code == 400

    async def test_cannot_revoke_already_revoked(self):
        db = make_db_multi(
            _execute_result(scalar=make_workspace()),
            _execute_result(scalar=make_invite(status="revoked")),
        )
        async with client_as(make_user(USER_ID), db) as ac:
            resp = await ac.delete(REVOKE_URL)
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# ACCEPT INVITE — functional + security
# ═══════════════════════════════════════════════════════════════════════════

class TestAcceptInvite:

    async def test_valid_accept_joins_workspace(self):
        db = make_db_multi(
            _execute_result(scalar=make_invite()),  # invite found
            _execute_result(scalar=None),            # not already a member
        )
        async with client_as(make_user(OTHER_USER_ID, VALID_EMAIL), db) as ac:
            resp = await ac.post(ACCEPT_URL, json={"token": VALID_TOKEN})
        assert resp.status_code == 200
        assert resp.json()["workspace_id"] == WORKSPACE_ID
        assert resp.json()["role"] == "collaborator"

    async def test_invalid_token_returns_generic_error(self):
        """Generic 400 — must not reveal whether token exists (A01 enumeration)."""
        db = make_db_multi(_execute_result(scalar=None))
        async with client_as(make_user(OTHER_USER_ID, VALID_EMAIL), db) as ac:
            resp = await ac.post(ACCEPT_URL, json={"token": "invalid-garbage"})
        assert resp.status_code == 400
        assert "Invalid or expired" in resp.json()["detail"]

    async def test_revoked_invite_rejected(self):
        db = make_db_multi(
            _execute_result(scalar=make_invite(status="revoked")),
        )
        async with client_as(make_user(OTHER_USER_ID, VALID_EMAIL), db) as ac:
            resp = await ac.post(ACCEPT_URL, json={"token": VALID_TOKEN})
        assert resp.status_code == 400

    async def test_expired_invite_rejected(self):
        db = make_db_multi(
            _execute_result(scalar=make_invite(expired=True)),
        )
        async with client_as(make_user(OTHER_USER_ID, VALID_EMAIL), db) as ac:
            resp = await ac.post(ACCEPT_URL, json={"token": VALID_TOKEN})
        assert resp.status_code == 400

    async def test_accept_does_not_mutate_caller_role(self):
        """Accepting an invite must not change the caller's platform role.

        Guards against future regressions where accept_invite might assign
        UserRole.COLLABORATOR to the authenticated user object.
        """
        db = make_db_multi(
            _execute_result(scalar=make_invite()),
            _execute_result(scalar=None),  # not already a member
        )
        user = make_user(OTHER_USER_ID, VALID_EMAIL)
        user.role = UserRole.RESEARCHER
        original_role = user.role

        async with client_as(user, db) as ac:
            resp = await ac.post(ACCEPT_URL, json={"token": VALID_TOKEN})

        assert resp.status_code == 200
        assert user.role == original_role

    async def test_already_member_is_idempotent(self):
        """Second accept (race condition / retry) succeeds without duplicate insert."""
        db = make_db_multi(
            _execute_result(scalar=make_invite()),
            _execute_result(scalar=MagicMock()),  # already a member
        )
        async with client_as(make_user(OTHER_USER_ID, VALID_EMAIL), db) as ac:
            resp = await ac.post(ACCEPT_URL, json={"token": VALID_TOKEN})
        assert resp.status_code == 200
        # db.add should NOT have been called with a WorkspaceMember
        from app.models.workspace import WorkspaceMember
        member_adds = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], WorkspaceMember)
        ]
        assert len(member_adds) == 0
