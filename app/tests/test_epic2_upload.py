"""
Test skeletons for Ticket 2.1 — Document Upload API.

Covers:
  - Successful PDF / DOCX / TXT uploads
  - SHA-256 hash correctness
  - Duplicate file detection via hash
  - Invalid file type rejection
  - File size limit enforcement
  - Document-not-found handling
  - Audit log entry created after upload

Tests use SQLite in-memory via the `db` fixture defined in conftest.py.
Filesystem writes are redirected to a pytest `tmp_path` fixture to avoid
touching production storage paths.
"""

import hashlib
import io
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.models import Document, DocumentClassification, DocumentStatus
from app.services import upload_service
from app.services.exceptions import DuplicateFileError, InvalidFileTypeError, NotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_upload_file(filename: str, content: bytes, content_type: str) -> MagicMock:
    """Return a minimal UploadFile mock compatible with upload_service."""
    mock = MagicMock()
    mock.filename = filename
    mock.content_type = content_type
    mock.file = io.BytesIO(content)
    mock.file.read = lambda: content
    return mock


def _make_document(db, title: str = "Test Doc") -> Document:
    doc = Document(title=title, status=DocumentStatus.DRAFT)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _patch_settings(storage_path: str, max_bytes: int = 52_428_800):
    """Context manager that patches upload_service.settings."""
    mock_cfg = MagicMock()
    mock_cfg.storage_path = storage_path
    mock_cfg.max_file_size_bytes = max_bytes
    return patch.object(upload_service, "settings", mock_cfg)


# ---------------------------------------------------------------------------
# Allowed file types
# ---------------------------------------------------------------------------

class TestAllowedFileTypes:
    def test_allowed_mime_types_registered(self):
        assert "application/pdf" in upload_service.ALLOWED_MIME_TYPES
        assert (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            in upload_service.ALLOWED_MIME_TYPES
        )
        assert "text/plain" in upload_service.ALLOWED_MIME_TYPES

    def test_allowed_extensions_set(self):
        assert ".pdf" in upload_service.ALLOWED_EXTENSIONS
        assert ".docx" in upload_service.ALLOWED_EXTENSIONS
        assert ".txt" in upload_service.ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Successful uploads
# ---------------------------------------------------------------------------

class TestUploadSuccess:
    def test_txt_upload_stores_metadata(self, db, tmp_path):
        doc = _make_document(db)
        content = b"hello veritas"
        upload = _make_upload_file("notes.txt", content, "text/plain")

        with _patch_settings(str(tmp_path)):
            result = upload_service.upload_document(
                db, doc.id, upload, DocumentClassification.PUBLIC
            )

        assert result.file_hash == hashlib.sha256(content).hexdigest()
        assert result.file_size == len(content)
        assert result.mime_type == "text/plain"
        assert result.classification == DocumentClassification.PUBLIC
        assert result.file_path.endswith("notes.txt")

    def test_pdf_upload_stores_metadata(self, db, tmp_path):
        doc = _make_document(db)
        content = b"%PDF-1.4 fake payload"
        upload = _make_upload_file("report.pdf", content, "application/pdf")

        with _patch_settings(str(tmp_path)):
            result = upload_service.upload_document(
                db, doc.id, upload, DocumentClassification.INTERNAL
            )

        assert result.classification == DocumentClassification.INTERNAL
        assert result.mime_type == "application/pdf"

    def test_docx_upload_stores_metadata(self, db, tmp_path):
        doc = _make_document(db)
        content = b"PK fake docx bytes"
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        upload = _make_upload_file("spec.docx", content, mime)

        with _patch_settings(str(tmp_path)):
            result = upload_service.upload_document(
                db, doc.id, upload, DocumentClassification.CONFIDENTIAL
            )

        assert result.classification == DocumentClassification.CONFIDENTIAL
        assert result.mime_type == mime

    def test_file_written_to_disk(self, db, tmp_path):
        doc = _make_document(db)
        content = b"disk write test"
        upload = _make_upload_file("data.txt", content, "text/plain")

        with _patch_settings(str(tmp_path)):
            result = upload_service.upload_document(
                db, doc.id, upload, DocumentClassification.PUBLIC
            )

        assert Path(result.file_path).exists()
        assert Path(result.file_path).read_bytes() == content

    def test_audit_log_created_after_upload(self, db, tmp_path):
        from app.models.models import AuditLog

        doc = _make_document(db)
        content = b"audit test"
        upload = _make_upload_file("audit.txt", content, "text/plain")

        with _patch_settings(str(tmp_path)):
            upload_service.upload_document(
                db, doc.id, upload, DocumentClassification.INTERNAL
            )

        log = (
            db.query(AuditLog)
            .filter(AuditLog.document_id == doc.id)
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert log is not None
        assert "uploaded" in log.action.lower()


# ---------------------------------------------------------------------------
# Hash correctness
# ---------------------------------------------------------------------------

class TestHashBehaviour:
    def test_sha256_is_correct(self, db, tmp_path):
        doc = _make_document(db)
        content = b"deterministic payload"
        expected = hashlib.sha256(content).hexdigest()
        upload = _make_upload_file("hash_check.txt", content, "text/plain")

        with _patch_settings(str(tmp_path)):
            result = upload_service.upload_document(
                db, doc.id, upload, DocumentClassification.PUBLIC
            )

        assert result.file_hash == expected
        assert len(result.file_hash) == 64  # 256-bit hex

    def test_same_file_same_document_rereplaces(self, db, tmp_path):
        """Re-uploading the same file to the same document should succeed (no duplicate error)."""
        doc = _make_document(db)
        content = b"same file same doc"
        upload1 = _make_upload_file("f.txt", content, "text/plain")

        with _patch_settings(str(tmp_path)):
            upload_service.upload_document(db, doc.id, upload1, DocumentClassification.PUBLIC)

        upload2 = _make_upload_file("f.txt", content, "text/plain")
        with _patch_settings(str(tmp_path)):
            result = upload_service.upload_document(
                db, doc.id, upload2, DocumentClassification.PUBLIC
            )

        assert result.file_hash == hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

class TestDuplicateDetection:
    def test_same_hash_different_document_rejected(self, db, tmp_path):
        doc1 = _make_document(db, "Doc 1")
        doc2 = _make_document(db, "Doc 2")
        content = b"identical bytes"

        upload1 = _make_upload_file("f.txt", content, "text/plain")
        with _patch_settings(str(tmp_path)):
            upload_service.upload_document(db, doc1.id, upload1, DocumentClassification.PUBLIC)

        upload2 = _make_upload_file("f.txt", content, "text/plain")
        with _patch_settings(str(tmp_path)):
            with pytest.raises(DuplicateFileError, match=doc1.id):
                upload_service.upload_document(
                    db, doc2.id, upload2, DocumentClassification.PUBLIC
                )

    def test_different_content_different_hash_allowed(self, db, tmp_path):
        doc1 = _make_document(db, "Doc A")
        doc2 = _make_document(db, "Doc B")

        with _patch_settings(str(tmp_path)):
            upload_service.upload_document(
                db, doc1.id,
                _make_upload_file("a.txt", b"content A", "text/plain"),
                DocumentClassification.PUBLIC,
            )
            result = upload_service.upload_document(
                db, doc2.id,
                _make_upload_file("b.txt", b"content B", "text/plain"),
                DocumentClassification.PUBLIC,
            )

        assert result.id == doc2.id


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class TestValidationErrors:
    def test_invalid_extension_rejected(self, db):
        doc = _make_document(db)
        upload = _make_upload_file("malware.exe", b"bad", "application/octet-stream")

        with pytest.raises(InvalidFileTypeError, match="extension"):
            upload_service.upload_document(db, doc.id, upload, DocumentClassification.PUBLIC)

    def test_wrong_mime_type_rejected(self, db):
        doc = _make_document(db)
        # Extension is .pdf but MIME is wrong
        upload = _make_upload_file("trick.pdf", b"bad", "application/octet-stream")

        with pytest.raises(InvalidFileTypeError):
            upload_service.upload_document(db, doc.id, upload, DocumentClassification.INTERNAL)

    def test_file_size_limit_enforced(self, db):
        doc = _make_document(db)
        content = b"x" * 200
        upload = _make_upload_file("big.txt", content, "text/plain")

        with _patch_settings("/tmp", max_bytes=100):
            with pytest.raises(InvalidFileTypeError, match="too large"):
                upload_service.upload_document(
                    db, doc.id, upload, DocumentClassification.INTERNAL
                )

    def test_document_not_found_raises(self, db):
        import uuid
        upload = _make_upload_file("doc.pdf", b"%PDF", "application/pdf")

        with pytest.raises(NotFoundError):
            upload_service.upload_document(
                db, str(uuid.uuid4()), upload, DocumentClassification.PUBLIC
            )


# ---------------------------------------------------------------------------
# Cleanup on DB failure
# ---------------------------------------------------------------------------

class TestAtomicCommit:
    def test_file_removed_when_db_commit_fails(self, db, tmp_path):
        doc = _make_document(db)
        content = b"transactional test"
        upload = _make_upload_file("tx.txt", content, "text/plain")

        written_paths: list[str] = []

        original_write_bytes = Path.write_bytes

        def _spy_write(self, data):
            written_paths.append(str(self))
            return original_write_bytes(self, data)

        with _patch_settings(str(tmp_path)):
            with patch.object(Path, "write_bytes", _spy_write):
                with patch.object(db, "commit", side_effect=RuntimeError("simulated DB error")):
                    with pytest.raises(RuntimeError, match="simulated DB error"):
                        upload_service.upload_document(
                            db, doc.id, upload, DocumentClassification.PUBLIC
                        )

        # The file that was written should have been cleaned up
        for p in written_paths:
            assert not os.path.exists(p), f"Orphaned file not cleaned up: {p}"
