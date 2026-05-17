from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.fire.domain.entities.document import Document, DocumentStatus, DocumentType

USER_ID = uuid4()


def _make_doc(**kwargs) -> Document:
    defaults = dict(
        user_id=USER_ID,
        filename="statement.pdf",
        file_path="/uploads/statement.pdf",
        file_hash="abc123",
    )
    return Document.create(**{**defaults, **kwargs})


def test_document_create_returns_pending_status() -> None:
    assert _make_doc().status == DocumentStatus.PENDING


def test_document_create_assigns_uuid() -> None:
    assert isinstance(_make_doc().id, UUID)


def test_document_create_sets_uploaded_at() -> None:
    before = datetime.now(UTC)
    doc = _make_doc()
    after = datetime.now(UTC)
    assert before <= doc.uploaded_at <= after


def test_document_create_defaults_to_unknown_type() -> None:
    assert _make_doc().document_type == DocumentType.UNKNOWN


def test_document_create_with_explicit_type() -> None:
    doc = _make_doc(document_type=DocumentType.BANK_STATEMENT)
    assert doc.document_type == DocumentType.BANK_STATEMENT


def test_document_belongs_to_user() -> None:
    assert _make_doc().user_id == USER_ID


def test_mark_processing_changes_status() -> None:
    doc = _make_doc()
    doc.mark_processing()
    assert doc.status == DocumentStatus.PROCESSING


def test_mark_processed_sets_status_and_timestamp() -> None:
    doc = _make_doc()
    before = datetime.now(UTC)
    doc.mark_processed()
    after = datetime.now(UTC)
    assert doc.status == DocumentStatus.PROCESSED
    assert doc.processed_at is not None
    assert before <= doc.processed_at <= after


def test_mark_failed_sets_status_and_message() -> None:
    doc = _make_doc()
    doc.mark_failed("LLM timeout")
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_message == "LLM timeout"


def test_is_duplicate_returns_true_for_matching_hash() -> None:
    assert _make_doc(file_hash="deadbeef").is_duplicate_of("deadbeef") is True


def test_is_duplicate_returns_false_for_different_hash() -> None:
    assert _make_doc(file_hash="deadbeef").is_duplicate_of("cafebabe") is False


def test_is_duplicate_returns_false_when_no_hash() -> None:
    assert _make_doc(file_hash="").is_duplicate_of("anything") is False
