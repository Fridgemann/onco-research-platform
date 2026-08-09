"""
Dataset endpoint security tests.

Organised by OWASP Top 10:2025 category so findings map directly to a report.

Run:
    cd backend
    pytest tests/test_dataset_security.py -v --asyncio-mode=auto
"""
import io
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token

from tests.conftest import (
    WORKSPACE_ID, OTHER_WS_ID, DATASET_ID, USER_ID, OTHER_USER_ID,
    make_db, make_member, make_dataset, authed_client,
    _execute_result,
)
from app.models.workspace import MemberRole

# ═══════════════════════════════════════════════════════════════════════════
# A01 — BROKEN ACCESS CONTROL
# ═══════════════════════════════════════════════════════════════════════════

class TestA01_Authentication:
    """Verify that the Bearer token is validated before any data is touched."""

    async def test_no_token_returns_403(self):
        """HTTPBearer rejects requests with no Authorization header."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/workspaces/{WORKSPACE_ID}/datasets",
                files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
            )
        assert resp.status_code == 403

    async def test_refresh_token_rejected_as_access(self):
        """A refresh token must not be accepted as a Bearer access token (A01/A07)."""
        token = create_refresh_token(USER_ID)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/workspaces/{WORKSPACE_ID}/datasets",
                files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 401

    async def test_tampered_jwt_rejected(self):
        """A token with a modified payload must be rejected (signature mismatch)."""
        token = create_access_token(USER_ID, "researcher")
        parts = token.split(".")
        # flip last char of payload to break signature
        parts[1] = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
        bad_token = ".".join(parts)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/workspaces/{WORKSPACE_ID}/datasets",
                files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
                headers={"Authorization": f"Bearer {bad_token}"},
            )
        assert resp.status_code == 401

    async def test_alg_none_attack_rejected(self):
        """JWT with alg=none must not validate (python-jose rejects it)."""
        import base64, json
        header  = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(json.dumps({"sub": USER_ID, "role": "researcher", "type": "access"}).encode()).rstrip(b"=").decode()
        none_token = f"{header}.{payload}."

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/workspaces/{WORKSPACE_ID}/datasets",
                files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
                headers={"Authorization": f"Bearer {none_token}"},
            )
        assert resp.status_code == 401


class TestA01_WorkspaceMembership:
    """Users may only access datasets inside workspaces they belong to."""

    async def test_non_member_upload_returns_403(self):
        """A valid user who is NOT a workspace member cannot upload."""
        db = make_db(_execute_result(scalar=None))  # _require_member returns None
        async with authed_client(db) as ac:
            resp = await ac.post(
                f"/api/workspaces/{WORKSPACE_ID}/datasets",
                files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
            )
        assert resp.status_code == 403

    async def test_non_member_list_returns_403(self):
        db = make_db(_execute_result(scalar=None))
        async with authed_client(db) as ac:
            resp = await ac.get(f"/api/workspaces/{WORKSPACE_ID}/datasets")
        assert resp.status_code == 403

    async def test_non_member_download_returns_403(self):
        db = make_db(_execute_result(scalar=None))
        async with authed_client(db) as ac:
            resp = await ac.get(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")
        assert resp.status_code == 403

    async def test_non_member_delete_returns_403(self):
        db = make_db(_execute_result(scalar=None))
        async with authed_client(db) as ac:
            resp = await ac.delete(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")
        assert resp.status_code == 403

    async def test_cross_workspace_idor_download(self):
        """
        IDOR: a member of workspace A cannot retrieve a dataset that belongs to
        workspace B, even when they guess the correct dataset_id.
        The route filters on (dataset_id AND workspace_id), so the query returns
        nothing and the response must be 404 — not 200.
        """
        member  = make_member(MemberRole.OWNER)
        # second execute returns no dataset (workspace_id mismatch)
        dataset = None
        db = make_db(_execute_result(scalar=member), _execute_result(scalar=dataset))

        async with authed_client(db) as ac:
            resp = await ac.get(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")
        assert resp.status_code == 404

    async def test_soft_deleted_dataset_not_accessible(self):
        """Soft-deleted datasets must return 404, not 200."""
        member = make_member(MemberRole.OWNER)
        # _require_member returns the member, but dataset query returns nothing
        # because route filters is_deleted == False
        db = make_db(_execute_result(scalar=member), _execute_result(scalar=None))
        async with authed_client(db) as ac:
            resp = await ac.get(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")
        assert resp.status_code == 404


class TestA01_DeletePermissions:
    """Delete is only allowed for the workspace OWNER or the file's uploader."""

    async def test_owner_can_delete_others_file(self):
        """Workspace owner may delete any dataset in their workspace."""
        owner_member = make_member(role=MemberRole.OWNER, user_id=USER_ID)
        # dataset uploaded by someone else
        ds = make_dataset(uploaded_by=OTHER_USER_ID)
        db = make_db(_execute_result(scalar=owner_member), _execute_result(scalar=ds))
        async with authed_client(db) as ac:
            resp = await ac.delete(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")
        assert resp.status_code == 200

    async def test_uploader_can_delete_own_file(self):
        """The user who uploaded the file may always delete it."""
        collaborator = make_member(role=MemberRole.COLLABORATOR, user_id=USER_ID)
        ds = make_dataset(uploaded_by=USER_ID)
        db = make_db(_execute_result(scalar=collaborator), _execute_result(scalar=ds))
        async with authed_client(db) as ac:
            resp = await ac.delete(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")
        assert resp.status_code == 200

    async def test_collaborator_cannot_delete_others_file(self):
        """A COLLABORATOR who did not upload the file must be denied (403)."""
        collaborator = make_member(role=MemberRole.COLLABORATOR, user_id=USER_ID)
        ds = make_dataset(uploaded_by=OTHER_USER_ID)  # different uploader
        db = make_db(_execute_result(scalar=collaborator), _execute_result(scalar=ds))
        async with authed_client(db) as ac:
            resp = await ac.delete(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")
        assert resp.status_code == 403

    async def test_double_delete_returns_404(self):
        """Second delete on an already-deleted dataset must return 404."""
        member = make_member(MemberRole.OWNER)
        # soft-deleted → route query returns nothing
        db = make_db(_execute_result(scalar=member), _execute_result(scalar=None))
        async with authed_client(db) as ac:
            resp = await ac.delete(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# A04 — INSECURE DESIGN (File Upload Validation)
# ═══════════════════════════════════════════════════════════════════════════

class TestA04_FileValidation:
    """Verify the upload validation gates — extension, MIME, size, magic bytes."""

    async def _upload(self, ac, filename, content, content_type):
        return await ac.post(
            f"/api/workspaces/{WORKSPACE_ID}/datasets",
            files={"file": (filename, io.BytesIO(content), content_type)},
        )

    async def test_disallowed_extension_rejected(self):
        """.exe files are rejected regardless of content-type."""
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        async with authed_client(db) as ac:
            resp = await self._upload(ac, "malware.exe", b"MZ\x90\x00", "application/octet-stream")
        assert resp.status_code == 400

    async def test_no_extension_rejected(self):
        """Filename with no extension is rejected."""
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        async with authed_client(db) as ac:
            resp = await self._upload(ac, "datafile", b"a,b\n1,2", "text/csv")
        assert resp.status_code == 400

    async def test_double_extension_last_wins(self):
        """
        double extension: os.path.splitext takes the LAST extension.
        'evil.exe.csv' → ext == '.csv' → PASSES validation.
        This is the current behaviour — document and decide if stricter
        validation (reject dots in stem) is needed.
        """
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        with patch("app.services.storage.upload_object", new_callable=AsyncMock):
            async with authed_client(db) as ac:
                resp = await self._upload(ac, "evil.exe.csv", b"a,b\n1,2", "text/csv")
        # documents current behaviour — update assertion if policy tightens
        assert resp.status_code == 201

    async def test_mime_mismatch_rejected(self):
        """Sending a .csv file with application/json content-type is rejected."""
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        async with authed_client(db) as ac:
            resp = await self._upload(ac, "data.csv", b"a,b\n1,2", "application/json")
        assert resp.status_code == 400

    async def test_xlsx_wrong_magic_bytes_rejected(self):
        """An .xlsx file that does NOT start with PK\\x03\\x04 is rejected."""
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        bad_xlsx = b"DEADBEEF" + b"\x00" * 100
        async with authed_client(db) as ac:
            resp = await self._upload(
                ac, "data.xlsx", bad_xlsx,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        assert resp.status_code == 400

    @pytest.mark.parametrize("filename,content_type", [
        ("data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("data.tsv", "text/tab-separated-values"),
        ("data.json", "application/json"),
    ])
    async def test_non_csv_uploads_rejected(self, filename, content_type):
        """Milestone 4: CSV only.

        Every read path parses with pd.read_csv, so these formats previously
        uploaded successfully and then failed on every analysis of the
        dataset. Rejecting at upload tells the researcher immediately. A
        well-formed .xlsx (correct PK magic bytes) is rejected too — the
        extension gate now runs first.
        """
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        payload = b"PK\x03\x04" + b"\x00" * 100 if filename.endswith(".xlsx") else b"a\tb\n1\t2"
        with patch("app.services.storage.upload_object", new_callable=AsyncMock):
            async with authed_client(db) as ac:
                resp = await self._upload(ac, filename, payload, content_type)
        assert resp.status_code == 400
        assert ".csv" in resp.json()["detail"]

    async def test_csv_upload_still_accepted(self):
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        with patch("app.services.storage.upload_object", new_callable=AsyncMock):
            async with authed_client(db) as ac:
                resp = await self._upload(ac, "data.csv", b"a,b\n1,2", "text/csv")
        assert resp.status_code == 201

    async def test_file_over_limit_rejected(self):
        """Files larger than MAX_FILE_SIZE (50 MB) must return 413."""
        from app.schemas.dataset import MAX_FILE_SIZE
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        oversized = b"a" * (MAX_FILE_SIZE + 1)
        async with authed_client(db) as ac:
            resp = await self._upload(ac, "big.csv", oversized, "text/csv")
        assert resp.status_code == 413

    async def test_file_exactly_at_limit_accepted(self):
        """A file exactly at MAX_FILE_SIZE must NOT be rejected (check is strictly >)."""
        from app.schemas.dataset import MAX_FILE_SIZE
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        exact = b"a" * MAX_FILE_SIZE
        with patch("app.services.storage.upload_object", new_callable=AsyncMock):
            async with authed_client(db) as ac:
                resp = await self._upload(ac, "exact.csv", exact, "text/csv")
        assert resp.status_code == 201

    async def test_empty_file_accepted(self):
        """
        Empty file (0 bytes) currently passes all validation gates.
        This is a documentation test — decide if empty files should be rejected.
        """
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        with patch("app.services.storage.upload_object", new_callable=AsyncMock):
            async with authed_client(db) as ac:
                resp = await self._upload(ac, "empty.csv", b"", "text/csv")
        # documents current behaviour
        assert resp.status_code == 201

    async def test_missing_content_type_bypasses_mime_check(self):
        """
        When the client sends no Content-Type, MIME validation is skipped.
        This is a documentation test — consider enforcing Content-Type presence.
        OWASP note: trusting client-supplied Content-Type at all is weak;
        magic bytes checks (like xlsx) are more reliable.
        """
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        with patch("app.services.storage.upload_object", new_callable=AsyncMock):
            async with authed_client(db) as ac:
                # httpx sends no Content-Type when content_type is None
                resp = await ac.post(
                    f"/api/workspaces/{WORKSPACE_ID}/datasets",
                    files={"file": ("data.csv", io.BytesIO(b"a,b\n1,2"), None)},
                )
        # documents current behaviour (201 = passes)
        assert resp.status_code == 201


# ═══════════════════════════════════════════════════════════════════════════
# A03 — INJECTION (Filename / Header Injection)
# ═══════════════════════════════════════════════════════════════════════════

class TestA03_Injection:
    """Filenames with injection payloads must not corrupt HTTP headers or storage paths."""

    async def test_crlf_injection_in_content_disposition(self):
        """
        A filename containing \\r\\n must not inject extra HTTP headers
        in the download Content-Disposition.

        Attack vector: filename = "evil\\r\\nX-Injected: pwned.csv"
        """
        malicious_filename = "evil\r\nX-Injected: pwned.csv"
        ds = make_dataset()
        # Override the decrypted filename to return the malicious value
        member = make_member()
        db = make_db(_execute_result(scalar=member), _execute_result(scalar=ds))

        with (
            patch("app.api.routes.dataset.decrypt_field", return_value=malicious_filename),
            patch("app.services.storage.download_object", new_callable=AsyncMock, return_value=b"encrypted"),
            patch("app.api.routes.dataset.decrypt_bytes", return_value=b"a,b\n1,2"),
        ):
            async with authed_client(db) as ac:
                resp = await ac.get(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")

        # The injected header must NOT appear in the response
        assert "X-Injected" not in resp.headers
        # The Content-Disposition must exist and be a single-line value
        cd = resp.headers.get("content-disposition", "")
        assert "\r" not in cd
        assert "\n" not in cd

    async def test_null_byte_in_filename_handled(self):
        """
        Filenames with null bytes are URL-encoded by urllib.parse.quote,
        so they must not cause errors or path confusion downstream.
        """
        null_filename = "evil\x00.csv"
        ds = make_dataset()
        member = make_member()
        db = make_db(_execute_result(scalar=member), _execute_result(scalar=ds))

        with (
            patch("app.api.routes.dataset.decrypt_field", return_value=null_filename),
            patch("app.services.storage.download_object", new_callable=AsyncMock, return_value=b"enc"),
            patch("app.api.routes.dataset.decrypt_bytes", return_value=b"a,b\n1,2"),
        ):
            async with authed_client(db) as ac:
                resp = await ac.get(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")

        # Must not 500
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        # Null byte must be percent-encoded, not literal
        assert "\x00" not in cd

    async def test_path_traversal_in_workspace_id(self):
        """
        workspace_id containing path traversal (../../) should not be routable.
        FastAPI's URL routing won't match it as a valid UUID segment.
        """
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            token = create_access_token(USER_ID, "researcher")
            resp = await ac.post(
                "/api/workspaces/../../etc/passwd/datasets",
                files={"file": ("data.csv", b"a", "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
        # 307 redirect, 404, 401, 403 are all acceptable — 200 is not
        assert resp.status_code != 200


# ═══════════════════════════════════════════════════════════════════════════
# A02 — CRYPTOGRAPHIC FAILURES
# ═══════════════════════════════════════════════════════════════════════════

class TestA02_Encryption:
    """Verify that files and filenames are never stored in plaintext."""

    async def test_file_content_encrypted_before_storage(self):
        """
        The bytes passed to storage.upload_object must differ from the
        original file content — Fernet ciphertext is never equal to plaintext.
        """
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        original_bytes = b"patient_id,diagnosis\n1,NSCLC\n"
        captured = {}

        async def fake_upload(key, data, content_type):
            captured["data"] = data

        with patch("app.services.storage.upload_object", side_effect=fake_upload):
            async with authed_client(db) as ac:
                await ac.post(
                    f"/api/workspaces/{WORKSPACE_ID}/datasets",
                    files={"file": ("data.csv", io.BytesIO(original_bytes), "text/csv")},
                )

        assert "data" in captured, "upload_object was never called"
        assert captured["data"] != original_bytes, "File stored as plaintext — not encrypted"

    async def test_filename_encrypted_in_db(self):
        """
        The filename stored in dataset.filename_encrypted must not equal
        the original filename (it must be Fernet ciphertext).
        """
        member = make_member()
        db = make_db(_execute_result(scalar=member))
        original_filename = "patients_2024.csv"
        stored_datasets = []

        def capture_add(obj):
            from app.models.dataset import Dataset
            from datetime import datetime, timezone
            if isinstance(obj, Dataset):
                if obj.created_at is None:
                    obj.created_at = datetime.now(timezone.utc)
                stored_datasets.append(obj)
        db.add.side_effect = capture_add

        with patch("app.services.storage.upload_object", new_callable=AsyncMock):
            async with authed_client(db) as ac:
                await ac.post(
                    f"/api/workspaces/{WORKSPACE_ID}/datasets",
                    files={"file": (original_filename, io.BytesIO(b"a,b\n1,2"), "text/csv")},
                )

        assert stored_datasets, "Dataset was never added to the DB session"
        stored_name = stored_datasets[0].filename_encrypted
        assert stored_name != original_filename, "Filename stored as plaintext — not encrypted"

    async def test_decrypted_content_matches_original_on_download(self):
        """
        Round-trip: encrypt then decrypt must return the original bytes.
        Tests that encrypt_bytes / decrypt_bytes are inverses.
        """
        from app.core.security import encrypt_bytes, decrypt_bytes
        original = b"patient_id,diagnosis\n42,glioblastoma\n"
        assert decrypt_bytes(encrypt_bytes(original)) == original


# ═══════════════════════════════════════════════════════════════════════════
# A09 — LOGGING FAILURES
# ═══════════════════════════════════════════════════════════════════════════

class TestA09_AuditLogging:
    """Security-relevant operations must be audit-logged."""

    async def test_upload_writes_audit_log(self):
        """Successful upload must call write_audit_log with DATASET_UPLOADED."""
        from app.models.audit_log import AuditAction
        member = make_member()
        db = make_db(_execute_result(scalar=member))

        with (
            patch("app.services.storage.upload_object", new_callable=AsyncMock),
            patch("app.api.routes.dataset.write_audit_log", new_callable=AsyncMock) as mock_audit,
        ):
            async with authed_client(db) as ac:
                await ac.post(
                    f"/api/workspaces/{WORKSPACE_ID}/datasets",
                    files={"file": ("data.csv", io.BytesIO(b"a,b\n1,2"), "text/csv")},
                )

        mock_audit.assert_awaited_once()
        _, kwargs = mock_audit.call_args
        assert kwargs.get("action") == AuditAction.DATASET_UPLOADED or \
               mock_audit.call_args[0][1] == AuditAction.DATASET_UPLOADED

    async def test_download_writes_audit_log(self):
        """Successful download must call write_audit_log with DATASET_DOWNLOADED."""
        from app.models.audit_log import AuditAction
        member = make_member()
        ds = make_dataset()
        db = make_db(_execute_result(scalar=member), _execute_result(scalar=ds))

        with (
            patch("app.services.storage.download_object", new_callable=AsyncMock, return_value=b"enc"),
            patch("app.api.routes.dataset.decrypt_bytes", return_value=b"a,b\n1,2"),
            patch("app.api.routes.dataset.write_audit_log", new_callable=AsyncMock) as mock_audit,
        ):
            async with authed_client(db) as ac:
                await ac.get(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")

        mock_audit.assert_awaited_once()

    async def test_delete_writes_audit_log(self):
        """Successful delete must call write_audit_log with DATASET_DELETED."""
        from app.models.audit_log import AuditAction
        member = make_member(MemberRole.OWNER)
        ds = make_dataset(uploaded_by=USER_ID)
        db = make_db(_execute_result(scalar=member), _execute_result(scalar=ds))

        with patch("app.api.routes.dataset.write_audit_log", new_callable=AsyncMock) as mock_audit:
            async with authed_client(db) as ac:
                await ac.delete(f"/api/workspaces/{WORKSPACE_ID}/datasets/{DATASET_ID}")

        mock_audit.assert_awaited_once()

    async def test_failed_auth_does_not_reach_audit_log(self):
        """A request with no token must fail before any audit log is written."""
        with patch("app.services.audit.write_audit_log", new_callable=AsyncMock) as mock_audit:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                await ac.post(
                    f"/api/workspaces/{WORKSPACE_ID}/datasets",
                    files={"file": ("data.csv", b"a,b", "text/csv")},
                )
        mock_audit.assert_not_awaited()
