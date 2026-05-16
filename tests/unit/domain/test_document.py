from datetime import UTC, datetime
from uuid import UUID

from src.fire.domain.entities.document import Document, DocumentStatus, DocumentType


def test_document_create_returns_pending_status():
    doc = Document.create(
        filename="statement.pdf",
        file_path="/uploads/statement.pdf",
        file_hash="abc123",
    )
    assert doc.status == DocumentStatus.PENDING


def test_document_create_assigns_uuid():
    doc = Document.create("x.pdf", "/uploads/x.pdf", "hash1")
    assert isinstance(doc.id, UUID)


def test_document_create_sets_uploaded_at():
    before = datetime.now(UTC)
    doc = Document.create("x.pdf", "/uploads/x.pdf", "hash1")
    after = datetime.now(UTC)
    assert before <= doc.uploaded_at <= after


def test_document_create_defaults_to_unknown_type():
    doc = Document.create("x.pdf", "/uploads/x.pdf", "hash1")
    assert doc.document_type == DocumentType.UNKNOWN


def test_document_create_with_explicit_type():
    doc = Document.create(
        "statement.pdf",
        "/uploads/statement.pdf",
        "hash1",
        document_type=DocumentType.BANK_STATEMENT,
    )
    assert doc.document_type == DocumentType.BANK_STATEMENT


def test_mark_processing_changes_status():
    doc = Document.create("x.pdf", "/uploads/x.pdf", "hash1")
    doc.mark_processing()
    assert doc.status == DocumentStatus.PROCESSING


def test_mark_processed_sets_status_and_timestamp():
    doc = Document.create("x.pdf", "/uploads/x.pdf", "hash1")
    before = datetime.now(UTC)
    doc.mark_processed()
    after = datetime.now(UTC)
    assert doc.status == DocumentStatus.PROCESSED
    assert doc.processed_at is not None
    assert before <= doc.processed_at <= after


def test_mark_failed_sets_status_and_message():
    doc = Document.create("x.pdf", "/uploads/x.pdf", "hash1")
    doc.mark_failed("LLM timeout")
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_message == "LLM timeout"


def test_is_duplicate_returns_true_for_matching_hash():
    doc = Document.create("x.pdf", "/uploads/x.pdf", "deadbeef")
    assert doc.is_duplicate_of("deadbeef") is True


def test_is_duplicate_returns_false_for_different_hash():
    doc = Document.create("x.pdf", "/uploads/x.pdf", "deadbeef")
    assert doc.is_duplicate_of("cafebabe") is False


def test_is_duplicate_returns_false_when_no_hash():
    doc = Document.create("x.pdf", "/uploads/x.pdf", "")
    assert doc.is_duplicate_of("anything") is False
