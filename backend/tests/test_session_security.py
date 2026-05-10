"""
Unit tests for absolute session lifetime enforcement.

Security rule: session lifetime is fixed at login time via session_iat.
Token rotation must NOT extend the session — exp = session_iat + 7 days, always.

Run:
    cd backend
    pytest tests/test_session_security.py -v
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport
from jose import jwt

from app.main import app
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_refresh_token

USER_ID = "aaaaaaaa-0000-0000-0000-000000000001"

REFRESH_URL = "/api/auth/refresh"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_active_user():
    u = MagicMock()
    u.id = USER_ID
    u.role = MagicMock()
    u.role.value = "researcher"
    u.is_active = True
    return u


def _make_db(user):
    db = MagicMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=r)
    return db


def _forge_token(session_iat: datetime | None = None, exp_offset_days: float = 1) -> str:
    """Build a refresh token manually, bypassing create_refresh_token."""
    payload = {
        "sub": USER_ID,
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=exp_offset_days),
        "iat": datetime.now(timezone.utc),
    }
    if session_iat is not None:
        payload["session_iat"] = session_iat.timestamp()
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


# ── Token creation ────────────────────────────────────────────────────────────

class TestTokenCreation:
    def test_session_iat_stored_in_payload(self):
        session_iat = datetime.now(timezone.utc) - timedelta(days=2)
        token = create_refresh_token(USER_ID, session_iat=session_iat)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert abs(payload["session_iat"] - session_iat.timestamp()) < 1

    def test_exp_equals_session_iat_plus_7_days(self):
        # verify_exp=False: inspecting payload structure, not current validity
        session_iat = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        token = create_refresh_token(USER_ID, session_iat=session_iat)
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False},
        )
        expected = session_iat + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        assert payload["exp"] == int(expected.timestamp())

    def test_two_rotations_same_session_iat_produce_same_exp(self):
        session_iat = datetime.now(timezone.utc) - timedelta(days=3)
        t1 = create_refresh_token(USER_ID, session_iat=session_iat)
        t2 = create_refresh_token(USER_ID, session_iat=session_iat)
        p1 = jwt.decode(t1, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        p2 = jwt.decode(t2, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert p1["exp"] == p2["exp"]

    def test_default_session_iat_is_now(self):
        before = datetime.now(timezone.utc)
        token = create_refresh_token(USER_ID)
        after = datetime.now(timezone.utc)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert before.timestamp() <= payload["session_iat"] <= after.timestamp()


# ── Refresh endpoint ──────────────────────────────────────────────────────────

class TestRefreshEndpoint:
    async def test_valid_session_iat_returns_200(self):
        token = create_refresh_token(USER_ID, session_iat=datetime.now(timezone.utc) - timedelta(days=1))
        db = _make_db(_make_active_user())
        app.dependency_overrides[get_db] = lambda: db
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(REFRESH_URL, cookies={"refresh_token": token})
            assert resp.status_code == 200
            assert "access_token" in resp.json()
        finally:
            app.dependency_overrides.pop(get_db, None)

    async def test_missing_session_iat_returns_401(self):
        token = _forge_token(session_iat=None)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(REFRESH_URL, cookies={"refresh_token": token})
        assert resp.status_code == 401

    async def test_expired_absolute_session_returns_401(self):
        # exp is in the future so jose accepts it — only our session_iat check should reject it
        session_iat = datetime.now(timezone.utc) - timedelta(days=8)
        token = _forge_token(session_iat=session_iat, exp_offset_days=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(REFRESH_URL, cookies={"refresh_token": token})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    async def test_rotated_token_preserves_session_iat(self):
        session_iat = datetime.now(timezone.utc) - timedelta(days=2)
        token = create_refresh_token(USER_ID, session_iat=session_iat)
        db = _make_db(_make_active_user())
        app.dependency_overrides[get_db] = lambda: db
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(REFRESH_URL, cookies={"refresh_token": token})
            assert resp.status_code == 200
            new_cookie = resp.cookies.get("refresh_token")
            assert new_cookie is not None, "rotated refresh_token cookie missing"
            new_payload = jwt.decode(new_cookie, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            assert abs(new_payload["session_iat"] - session_iat.timestamp()) < 1
        finally:
            app.dependency_overrides.pop(get_db, None)

    async def test_rotated_token_has_same_exp(self):
        session_iat = datetime.now(timezone.utc) - timedelta(days=2)
        original = create_refresh_token(USER_ID, session_iat=session_iat)
        original_exp = jwt.decode(original, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])["exp"]
        db = _make_db(_make_active_user())
        app.dependency_overrides[get_db] = lambda: db
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(REFRESH_URL, cookies={"refresh_token": original})
            assert resp.status_code == 200
            new_cookie = resp.cookies.get("refresh_token")
            new_payload = jwt.decode(new_cookie, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            assert new_payload["exp"] == original_exp
        finally:
            app.dependency_overrides.pop(get_db, None)

    async def test_refresh_cookie_is_session_only(self):
        # Set-Cookie must not contain Max-Age or Expires — session-only behavior
        token = create_refresh_token(USER_ID, session_iat=datetime.now(timezone.utc) - timedelta(days=1))
        db = _make_db(_make_active_user())
        app.dependency_overrides[get_db] = lambda: db
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(REFRESH_URL, cookies={"refresh_token": token})
            assert resp.status_code == 200
            set_cookie = resp.headers.get("set-cookie", "")
            assert "max-age" not in set_cookie.lower()
            assert "expires" not in set_cookie.lower()
        finally:
            app.dependency_overrides.pop(get_db, None)
