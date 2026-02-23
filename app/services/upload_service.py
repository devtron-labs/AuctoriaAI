"""
Service layer for Ticket 2.1 — Document Upload.

Responsibilities:
- Validate file type (PDF, DOCX, TXT) by extension AND MIME type
- Enforce file size limit (configurable via settings.max_file_size_bytes)
- Compute SHA-256 hash and detect duplicates
- Store file atomically at: {storage_path}/{document_id}/{filename}
- Update documents table columns: file_path, file_hash, classification,
  file_size, mime_type
- Write audit log entry
- Clean up stored file if the DB commit fails
"""

import hashlib
import logging
import os
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import AuditLog, Document, DocumentClassification
from app.services.exceptions import (
    DuplicateFileError,
    InvalidFileTypeError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

# Supported file types: (MIME type → canonical extension)
ALLOWED_MIME_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
}

ALLOWED_EXTENSIONS: frozenset[str] = frozenset(ALLOWED_MIME_TYPES.values())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audit(db: Session, document_id: str, action: str) -> None:
    log = AuditLog(document_id=document_id, action=action[:512])
    db.add(log)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def upload_document(
    db: Session,
    document_id: str,
    file: UploadFile,
    classification: DocumentClassification,
) -> Document:
    """
    Validate, store, and register an uploaded file against an existing document.

    Args:
        db:             SQLAlchemy session.
        document_id:    UUID string of the target Document row.
        file:           FastAPI UploadFile from the multipart request.
        classification: DocumentClassification enum value from form field.

    Returns:
        The updated Document ORM instance.

    Raises:
        NotFoundError:       document_id does not exist.
        InvalidFileTypeError: unsupported extension/MIME or file too large.
        DuplicateFileError:  another document already carries the same hash.
        OSError:             filesystem write failure.
    """
    logger.info("Upload started: document_id=%s classification=%s", document_id, classification)

    # ── 1. Verify document exists ─────────────────────────────────────────────
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    # ── 2. Validate file type (extension + MIME) ──────────────────────────────
    filename = file.filename or ""
    file_ext = Path(filename).suffix.lower()
    content_type = (file.content_type or "").split(";")[0].strip()  # strip charset params

    if file_ext not in ALLOWED_EXTENSIONS or content_type not in ALLOWED_MIME_TYPES:
        raise InvalidFileTypeError(
            f"Unsupported file: extension='{file_ext}', content_type='{content_type}'. "
            f"Allowed extensions: {sorted(ALLOWED_EXTENSIONS)}"
        )

    # ── 3. Read content and enforce size limit ────────────────────────────────
    contents: bytes = file.file.read()
    file_size = len(contents)

    if file_size > settings.max_file_size_bytes:
        raise InvalidFileTypeError(
            f"File too large: {file_size:,} bytes exceeds the "
            f"{settings.max_file_size_bytes:,}-byte limit"
        )

    # ── 4. Compute SHA-256 hash ───────────────────────────────────────────────
    file_hash = hashlib.sha256(contents).hexdigest()
    logger.info("SHA-256=%s size=%d document_id=%s", file_hash, file_size, document_id)

    # ── 5. Duplicate detection ────────────────────────────────────────────────
    duplicate = (
        db.query(Document)
        .filter(Document.file_hash == file_hash, Document.id != document_id)
        .first()
    )
    if duplicate is not None:
        raise DuplicateFileError(
            f"A file with hash {file_hash} already exists on document {duplicate.id}"
        )

    # ── 6. Write file to storage ──────────────────────────────────────────────
    storage_dir = Path(settings.storage_path) / document_id
    storage_dir.mkdir(parents=True, exist_ok=True)

    safe_filename = Path(filename).name or f"upload{file_ext}"
    dest_path = storage_dir / safe_filename

    try:
        dest_path.write_bytes(contents)
        logger.info("File written: path=%s", dest_path)
    except OSError as exc:
        logger.error("Filesystem write failed: document_id=%s error=%s", document_id, exc)
        raise

    # ── 7. Update document row + audit log (atomic) ───────────────────────────
    doc.file_path = str(dest_path)
    doc.file_hash = file_hash
    doc.classification = classification
    doc.file_size = file_size
    doc.mime_type = content_type

    _audit(
        db,
        document_id,
        f"File uploaded: filename='{safe_filename}' size={file_size} "
        f"hash={file_hash} classification={classification.value}",
    )

    try:
        db.commit()
        db.refresh(doc)
        logger.info("Upload committed: document_id=%s", document_id)
    except Exception:
        # Roll back the filesystem write to avoid orphaned files
        if dest_path.exists():
            os.remove(dest_path)
            logger.warning("Removed orphaned file after DB failure: path=%s", dest_path)
        raise

    return doc
