from datetime import date
from pathlib import Path

import pytest
from src.fire.application.use_cases.ingest_document import IngestDocument, IngestDocumentRequest
from src.fire.domain.entities.document import DocumentStatus, DocumentType

from tests.fakes import FakeDocumentRepository, FakeFileStorage


@pytest.fixture
def doc_repo() -> FakeDocumentRepository:
    return FakeDocumentRepository()


@pytest.fixture
def file_storage() -> FakeFileStorage:
    return FakeFileStorage()


@pytest.fixture
def use_case(doc_repo: FakeDocumentRepository, file_storage: FakeFileStorage) -> IngestDocument:
    return IngestDocument(document_repo=doc_repo, file_storage=file_storage)


@pytest.fixture
def pdf_request() -> IngestDocumentRequest:
    return IngestDocumentRequest(
        filename="january_statement.pdf",
        content=b"%PDF-fake-content",
        mime_type="application/pdf",
        upload_date=date(2024, 1, 15),
        document_type=DocumentType.BANK_STATEMENT,
    )


async def test_ingest_saves_file_to_daily_folder(
    use_case: IngestDocument,
    file_storage: FakeFileStorage,
    pdf_request: IngestDocumentRequest,
) -> None:
    result = await use_case.execute(pdf_request)
    stored = await file_storage.read(Path(result.file_path))
    assert stored == pdf_request.content


async def test_ingest_file_path_contains_dd_mm_folder(
    use_case: IngestDocument,
    pdf_request: IngestDocumentRequest,
) -> None:
    result = await use_case.execute(pdf_request)
    assert "15-01" in str(result.file_path)


async def test_ingest_creates_document_with_pending_status(
    use_case: IngestDocument,
    pdf_request: IngestDocumentRequest,
) -> None:
    result = await use_case.execute(pdf_request)
    assert result.status == DocumentStatus.PENDING


async def test_ingest_persists_document_to_repo(
    use_case: IngestDocument,
    doc_repo: FakeDocumentRepository,
    pdf_request: IngestDocumentRequest,
) -> None:
    result = await use_case.execute(pdf_request)
    saved = await doc_repo.get_by_id(result.id)
    assert saved is not None
    assert saved.id == result.id


async def test_ingest_stores_correct_document_type(
    use_case: IngestDocument,
    pdf_request: IngestDocumentRequest,
) -> None:
    result = await use_case.execute(pdf_request)
    assert result.document_type == DocumentType.BANK_STATEMENT


async def test_ingest_raises_on_duplicate_file(
    use_case: IngestDocument,
    pdf_request: IngestDocumentRequest,
) -> None:
    await use_case.execute(pdf_request)
    with pytest.raises(ValueError, match="duplicate"):
        await use_case.execute(pdf_request)


async def test_ingest_allows_different_files(
    use_case: IngestDocument,
    pdf_request: IngestDocumentRequest,
) -> None:
    second = IngestDocumentRequest(
        filename="february_statement.pdf",
        content=b"%PDF-different-content",
        mime_type="application/pdf",
        upload_date=date(2024, 2, 1),
        document_type=DocumentType.BANK_STATEMENT,
    )
    first = await use_case.execute(pdf_request)
    second_result = await use_case.execute(second)
    assert first.id != second_result.id


async def test_ingest_stores_file_hash_on_document(
    use_case: IngestDocument,
    doc_repo: FakeDocumentRepository,
    pdf_request: IngestDocumentRequest,
) -> None:
    result = await use_case.execute(pdf_request)
    saved = await doc_repo.get_by_id(result.id)
    assert saved is not None
    assert len(saved.file_hash) == 64  # sha256 hex digest
