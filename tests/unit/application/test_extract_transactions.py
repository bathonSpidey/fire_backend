from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from src.fire.application.use_cases.extract_transactions import (
    ExtractTransactions,
    ExtractTransactionsRequest,
)
from src.fire.domain.entities.document import Document, DocumentStatus, DocumentType
from src.fire.domain.entities.transaction import TransactionCategory, TransactionType
from src.fire.domain.interfaces.services import ExtractedTransaction, ExtractionResult

from tests.fakes import (
    FakeDocumentRepository,
    FakeFileStorage,
    FakeLLMDocumentParser,
    FakeTransactionRepository,
)

_UPLOAD_DATE = date(2024, 1, 15)
_FILE_CONTENT = b"%PDF-fake-content"
_FILE_NAME = "statement.pdf"


def _make_extraction_result(n: int = 2) -> ExtractionResult:
    return ExtractionResult(
        transactions=[
            ExtractedTransaction(
                date=date(2024, 1, i + 1),
                description=f"Transaction {i}",
                amount=Decimal("10.00") * (i + 1),
                transaction_type=TransactionType.DEBIT,
                category=TransactionCategory.GROCERIES,
            )
            for i in range(n)
        ],
        account_name="Main Checking",
        account_institution="Deutsche Bank",
        statement_period_start=date(2024, 1, 1),
        statement_period_end=date(2024, 1, 31),
        closing_balance=Decimal("1500.00"),
        raw_llm_response='{"transactions": []}',
    )


@pytest.fixture
def file_storage() -> FakeFileStorage:
    return FakeFileStorage()


@pytest.fixture
def doc_repo() -> FakeDocumentRepository:
    return FakeDocumentRepository()


@pytest.fixture
def tx_repo() -> FakeTransactionRepository:
    return FakeTransactionRepository()


@pytest.fixture
def llm_parser() -> FakeLLMDocumentParser:
    return FakeLLMDocumentParser(result=_make_extraction_result())


@pytest.fixture
async def saved_document(
    doc_repo: FakeDocumentRepository,
    file_storage: FakeFileStorage,
) -> Document:
    """Creates a document that has already been ingested (file exists in storage)."""
    file_path = await file_storage.save(_FILE_NAME, _FILE_CONTENT, _UPLOAD_DATE)
    doc = Document.create(
        filename=_FILE_NAME,
        file_path=str(file_path),
        file_hash="abc123",
        document_type=DocumentType.BANK_STATEMENT,
    )
    return await doc_repo.save(doc)


@pytest.fixture
def use_case(
    doc_repo: FakeDocumentRepository,
    tx_repo: FakeTransactionRepository,
    llm_parser: FakeLLMDocumentParser,
    file_storage: FakeFileStorage,
) -> ExtractTransactions:
    return ExtractTransactions(
        document_repo=doc_repo,
        transaction_repo=tx_repo,
        llm_parser=llm_parser,
        file_storage=file_storage,
    )


async def test_extract_returns_transactions(
    use_case: ExtractTransactions,
    saved_document: Document,
) -> None:
    result = await use_case.execute(ExtractTransactionsRequest(document_id=saved_document.id))
    assert len(result) == 2


async def test_extract_persists_transactions(
    use_case: ExtractTransactions,
    saved_document: Document,
    tx_repo: FakeTransactionRepository,
) -> None:
    await use_case.execute(ExtractTransactionsRequest(document_id=saved_document.id))
    saved = await tx_repo.get_by_document(saved_document.id)
    assert len(saved) == 2


async def test_extract_marks_document_as_processed(
    use_case: ExtractTransactions,
    saved_document: Document,
    doc_repo: FakeDocumentRepository,
) -> None:
    await use_case.execute(ExtractTransactionsRequest(document_id=saved_document.id))
    updated = await doc_repo.get_by_id(saved_document.id)
    assert updated is not None
    assert updated.status == DocumentStatus.PROCESSED


async def test_extract_marks_document_failed_when_llm_raises(
    doc_repo: FakeDocumentRepository,
    tx_repo: FakeTransactionRepository,
    file_storage: FakeFileStorage,
    saved_document: Document,
) -> None:
    broken_parser = FakeLLMDocumentParser(result=None)
    use_case = ExtractTransactions(
        document_repo=doc_repo,
        transaction_repo=tx_repo,
        llm_parser=broken_parser,
        file_storage=file_storage,
    )
    with pytest.raises(RuntimeError):
        await use_case.execute(ExtractTransactionsRequest(document_id=saved_document.id))
    updated = await doc_repo.get_by_id(saved_document.id)
    assert updated is not None
    assert updated.status == DocumentStatus.FAILED


async def test_extract_raises_when_document_not_found(
    use_case: ExtractTransactions,
) -> None:
    with pytest.raises(ValueError, match="not found"):
        await use_case.execute(ExtractTransactionsRequest(document_id=uuid4()))


async def test_extract_calls_llm_exactly_once(
    use_case: ExtractTransactions,
    saved_document: Document,
    llm_parser: FakeLLMDocumentParser,
) -> None:
    await use_case.execute(ExtractTransactionsRequest(document_id=saved_document.id))
    assert llm_parser.call_count == 1


async def test_extract_transaction_amounts_match_llm_output(
    use_case: ExtractTransactions,
    saved_document: Document,
    tx_repo: FakeTransactionRepository,
) -> None:
    await use_case.execute(ExtractTransactionsRequest(document_id=saved_document.id))
    saved = await tx_repo.get_by_document(saved_document.id)
    amounts = sorted(t.amount for t in saved)
    assert amounts == [Decimal("10.00"), Decimal("20.00")]
