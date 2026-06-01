"""
Login security tests.

Verifies that failed-login side-effects (attempt counter, lockout, audit logs)
persist even though the route raises HTTPException, which would normally
trigger get_db()'s rollback path.

Execute sequence for POST /api/auth/login:
  1. user lookup (User.email_hash)

Run:
    cd backend
    pytest tests/test_login_security.py -v
"""
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock, AsyncMock

from app.main import app
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import UserRole

from tests.conftest import USER_ID, _execute_result

# ── Constants ────────────────────────────────────────────────────────────────

LOGIN_URL      = "/api/auth/login"
VALID_EMAIL    = "researcher@hospital.org"
VALID_PASSWORD = "CorrectPass1!"
WRONG_PASSWORD = "WrongPass1!"


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_login_user(failed_attempts: int = 0, locked_until=None):
    u = MagicMock()
    u.id = USER_ID
    u.role = UserRole.RESEARCHER
    u.is_active = True
    u.email_hash = _email_hash(VALID_EMAIL)
    u.hashed_password = hash_password(VALID_PASSWORD)
    u.failed_login_attempts = failed_attempts
    u.locked_until = locked_until
    u.last_login = None
    return u


def make_login_db(user=None):
    db = MagicMock()
    db.execute = AsyncMock(return_value=_execute_result(scalar=user))
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


@asynccontextmanager
async def anon_client(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)


def _body(password: str = VALID_PASSWORD):
    return {"email": VALID_EMAIL, "password": password}


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.core.rate_limit import limiter
    limiter._storage.storage.clear()
    limiter._storage.expirations.clear()
    yield


# ═══════════════════════════════════════════════════════════════════════════
# FAILED LOGIN PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════

class TestFailedLoginPersistence:

    async def test_wrong_password_increments_attempts(self):
        """failed_login_attempts must be committed, not rolled back with the 401."""
        user = make_login_user(failed_attempts=0)
        db = make_login_db(user)
        async with anon_client(db) as ac:
            resp = await ac.post(LOGIN_URL, json=_body(WRONG_PASSWORD))
        assert resp.status_code == 401
        assert user.failed_login_attempts == 1
        db.commit.assert_called_once()

    async def test_fifth_wrong_password_sets_lockout(self):
        """5th failed attempt must set locked_until and be committed."""
        user = make_login_user(failed_attempts=4)
        db = make_login_db(user)
        async with anon_client(db) as ac:
            resp = await ac.post(LOGIN_URL, json=_body(WRONG_PASSWORD))
        assert resp.status_code == 401
        assert user.failed_login_attempts == 5
        assert user.locked_until is not None
        assert user.locked_until > datetime.now(timezone.utc)
        db.commit.assert_called_once()

    async def test_locked_account_audit_commits(self):
        """Audit log for a locked account must be committed before the 401."""
        from datetime import timedelta
        future = datetime.now(timezone.utc) + timedelta(minutes=10)
        user = make_login_user(locked_until=future)
        db = make_login_db(user)
        async with anon_client(db) as ac:
            resp = await ac.post(LOGIN_URL, json=_body(WRONG_PASSWORD))
        assert resp.status_code == 401
        db.commit.assert_called_once()

    async def test_unknown_email_audit_commits(self):
        """Audit log for unknown email must be committed before the 401."""
        db = make_login_db(user=None)
        async with anon_client(db) as ac:
            resp = await ac.post(LOGIN_URL, json=_body())
        assert resp.status_code == 401
        db.commit.assert_called_once()

    async def test_successful_login_resets_attempts(self):
        """Successful login zeroes failed_login_attempts and clears lockout."""
        user = make_login_user(failed_attempts=3)
        db = make_login_db(user)
        async with anon_client(db) as ac:
            resp = await ac.post(LOGIN_URL, json=_body(VALID_PASSWORD))
        assert resp.status_code == 200
        assert user.failed_login_attempts == 0
        assert user.locked_until is None
