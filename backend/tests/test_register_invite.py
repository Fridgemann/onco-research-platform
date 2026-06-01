"""
Invite-aware registration tests.

Execute sequence for POST /api/auth/register:
  - without invite_token: existing-user check only
  - with invite_token:    existing-user check → invite lookup

Run:
    cd backend
    pytest tests/test_register_invite.py -v
"""
import hashlib
import uuid as _uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_db
from app.models.user import User
from app.models.workspace import WorkspaceMember, MemberRole
from app.models.workspace_invite import InviteStatus

from tests.conftest import WORKSPACE_ID, _execute_result

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear in-memory rate limit counters so tests don't bleed into each other."""
    from app.core.rate_limit import limiter
    limiter._storage.storage.clear()
    limiter._storage.expirations.clear()
    yield

# ── Constants ───────────────────────────────────────────────────────────────

REGISTER_URL   = "/api/auth/register"
VALID_EMAIL    = "newuser@hospital.org"
OTHER_EMAIL    = "other@institution.org"
VALID_TOKEN    = "invite_token_plaintext_value"
INVITER_ID     = "aaaaaaaa-0000-0000-0000-000000000099"
VALID_PASSWORD = "StrongPass1!"


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


# ── Helpers ─────────────────────────────────────────────────────────────────

def make_invite(
    email: str = VALID_EMAIL,
    status: str = "pending",
    expired: bool = False,
):
    inv = MagicMock()
    inv.id = str(_uuid.uuid4())
    inv.workspace_id = WORKSPACE_ID
    inv.invited_email_hash = _email_hash(email)
    inv.token_hash = hashlib.sha256(VALID_TOKEN.encode()).hexdigest()
    inv.status = InviteStatus(status)
    inv.invited_by = INVITER_ID
    inv.expires_at = (
        datetime.now(timezone.utc) - timedelta(days=1)
        if expired
        else datetime.now(timezone.utc) + timedelta(days=7)
    )
    inv.accepted_at = None
    return inv


def make_register_db(*execute_results):
    """
    AsyncSession mock for the register endpoint.

    db.add() simulates SQLAlchemy INSERT defaults for User objects — id and
    created_at are set by column defaults only on real INSERT, so we inject
    them here to let _user_to_response() succeed.
    """
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(execute_results))
    db.flush = AsyncMock()

    def _add_with_defaults(obj):
        if isinstance(obj, User):
            if not obj.id:
                obj.id = str(_uuid.uuid4())
            if obj.is_active is None:
                obj.is_active = True
            if obj.is_verified is None:
                obj.is_verified = False
            if not obj.created_at:
                obj.created_at = datetime.now(timezone.utc)
            if not obj.updated_at:
                obj.updated_at = datetime.now(timezone.utc)

    db.add = MagicMock(side_effect=_add_with_defaults)
    return db


@asynccontextmanager
async def anon_client(db):
    """Client with only DB overridden — register is unauthenticated."""
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)


def _body(**overrides):
    return {"email": VALID_EMAIL, "full_name": "Dr. Test", "password": VALID_PASSWORD, **overrides}


# ═══════════════════════════════════════════════════════════════════════════
# NORMAL REGISTRATION (no invite_token)
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalRegister:

    async def test_creates_researcher_role(self):
        db = make_register_db(_execute_result(scalar=None))
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body())
        assert resp.status_code == 201
        assert resp.json()["user"]["role"] == "researcher"
        assert resp.json()["workspace_id"] is None

    async def test_duplicate_email_returns_409(self):
        db = make_register_db(_execute_result(scalar=MagicMock()))
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body())
        assert resp.status_code == 409

    async def test_weak_password_rejected(self):
        db = make_register_db()
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body(password="short"))
        assert resp.status_code == 422

    async def test_invalid_email_rejected(self):
        db = make_register_db()
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body(email="not-an-email"))
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# INVITE-AWARE REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════

class TestInviteRegister:

    async def test_valid_invite_creates_collaborator(self):
        """New user via invite gets COLLABORATOR role and workspace_id in response."""
        db = make_register_db(
            _execute_result(scalar=None),           # no existing user
            _execute_result(scalar=make_invite()),  # valid pending invite
        )
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body(invite_token=VALID_TOKEN))
        assert resp.status_code == 201
        body = resp.json()
        assert body["user"]["role"] == "collaborator"
        assert body["workspace_id"] == WORKSPACE_ID

    async def test_valid_invite_adds_workspace_member(self):
        """WorkspaceMember row must be passed to db.add()."""
        db = make_register_db(
            _execute_result(scalar=None),
            _execute_result(scalar=make_invite()),
        )
        async with anon_client(db) as ac:
            await ac.post(REGISTER_URL, json=_body(invite_token=VALID_TOKEN))

        member_adds = [
            call.args[0]
            for call in db.add.call_args_list
            if isinstance(call.args[0], WorkspaceMember)
        ]
        assert len(member_adds) == 1
        assert member_adds[0].workspace_id == WORKSPACE_ID
        assert member_adds[0].user_id is not None
        assert member_adds[0].role == MemberRole.COLLABORATOR
        assert member_adds[0].invited_by == INVITER_ID

    async def test_valid_invite_marks_accepted(self):
        """Invite status mutated to ACCEPTED with a timestamp."""
        invite = make_invite()
        db = make_register_db(
            _execute_result(scalar=None),
            _execute_result(scalar=invite),
        )
        async with anon_client(db) as ac:
            await ac.post(REGISTER_URL, json=_body(invite_token=VALID_TOKEN))

        assert invite.status == InviteStatus.ACCEPTED
        assert invite.accepted_at is not None

    async def test_expired_invite_returns_400(self):
        db = make_register_db(
            _execute_result(scalar=None),
            _execute_result(scalar=make_invite(expired=True)),
        )
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body(invite_token=VALID_TOKEN))
        assert resp.status_code == 400
        assert "Invalid or expired" in resp.json()["detail"]

    async def test_used_invite_returns_400(self):
        db = make_register_db(
            _execute_result(scalar=None),
            _execute_result(scalar=make_invite(status="accepted")),
        )
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body(invite_token=VALID_TOKEN))
        assert resp.status_code == 400

    async def test_revoked_invite_returns_400(self):
        db = make_register_db(
            _execute_result(scalar=None),
            _execute_result(scalar=make_invite(status="revoked")),
        )
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body(invite_token=VALID_TOKEN))
        assert resp.status_code == 400

    async def test_nonexistent_token_returns_400(self):
        """Token that matches no invite row → generic 400, no information leak."""
        db = make_register_db(
            _execute_result(scalar=None),   # no existing user
            _execute_result(scalar=None),   # no invite found
        )
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body(invite_token="garbage"))
        assert resp.status_code == 400
        assert "Invalid or expired" in resp.json()["detail"]

    async def test_wrong_email_returns_403(self):
        """Token valid but invite was for a different email address."""
        db = make_register_db(
            _execute_result(scalar=None),
            _execute_result(scalar=make_invite(email=OTHER_EMAIL)),
        )
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body(invite_token=VALID_TOKEN))
        assert resp.status_code == 403
        assert "different email" in resp.json()["detail"]

    async def test_declined_invite_returns_400(self):
        db = make_register_db(
            _execute_result(scalar=None),
            _execute_result(scalar=make_invite(status="declined")),
        )
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body(invite_token=VALID_TOKEN))
        assert resp.status_code == 400

    async def test_existing_email_with_invite_returns_409(self):
        """Email uniqueness check runs before invite validation."""
        db = make_register_db(_execute_result(scalar=MagicMock()))
        async with anon_client(db) as ac:
            resp = await ac.post(REGISTER_URL, json=_body(invite_token=VALID_TOKEN))
        assert resp.status_code == 409
        # invite lookup must NOT have been called — only 1 execute call
        assert db.execute.call_count == 1
