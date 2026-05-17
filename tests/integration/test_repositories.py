"""
Integration tests — hit real SQLite (in-memory).
These test that our ORM mappers, SQL queries, and constraints all work correctly.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker
from src.fire.domain.entities.account import Account, AccountType
from src.fire.domain.entities.budget_insight import BudgetInsight, SpendingBreakdown
from src.fire.domain.entities.document import Document, DocumentStatus, DocumentType
from src.fire.domain.entities.transaction import (
    Transaction,
    TransactionCategory,
    TransactionType,
)
from src.fire.domain.entities.user import User
from src.fire.infrastructure.db.session import build_test_session_factory
from src.fire.infrastructure.repositories.account_insight_repositories import (
    AccountRepository,
    InsightRepository,
)
from src.fire.infrastructure.repositories.document_repository import DocumentRepository
from src.fire.infrastructure.repositories.transaction_repository import (
    TransactionRepository,
)
from src.fire.infrastructure.repositories.user_repository import UserRepository


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    return build_test_session_factory()


@pytest.fixture
def user_repo(session_factory: sessionmaker[Session]) -> UserRepository:
    return UserRepository(session_factory)


@pytest.fixture
def doc_repo(session_factory: sessionmaker[Session]) -> DocumentRepository:
    return DocumentRepository(session_factory)


@pytest.fixture
def tx_repo(session_factory: sessionmaker[Session]) -> TransactionRepository:
    return TransactionRepository(session_factory)


@pytest.fixture
def account_repo(session_factory: sessionmaker[Session]) -> AccountRepository:
    return AccountRepository(session_factory)


@pytest.fixture
def insight_repo(session_factory: sessionmaker[Session]) -> InsightRepository:
    return InsightRepository(session_factory)


@pytest.fixture
async def saved_user(user_repo: UserRepository) -> User:
    return await user_repo.save(User.create("Alice"))


# ── User ────────────────────────────────────────────────────────────────────


async def test_user_save_and_retrieve(user_repo: UserRepository) -> None:
    user = await user_repo.save(User.create("Alice"))
    found = await user_repo.get_by_id(user.id)
    assert found is not None and found.name == "Alice"


async def test_user_list_all(user_repo: UserRepository) -> None:
    await user_repo.save(User.create("Alice"))
    await user_repo.save(User.create("Bob"))
    users = await user_repo.list_all()
    assert len(users) == 2


async def test_user_not_found_returns_none(user_repo: UserRepository) -> None:
    assert await user_repo.get_by_id(uuid4()) is None


# ── Document ─────────────────────────────────────────────────────────────────


async def test_document_save_and_retrieve(
    doc_repo: DocumentRepository, saved_user: User
) -> None:
    doc = Document.create(
        user_id=saved_user.id,
        filename="jan.pdf",
        file_path="files/15-01/jan.pdf",
        file_hash="abc123",
        document_type=DocumentType.BANK_STATEMENT,
    )
    saved = await doc_repo.save(doc)
    found = await doc_repo.get_by_id(saved.id)
    assert found is not None and found.filename == "jan.pdf"


async def test_document_get_by_hash(
    doc_repo: DocumentRepository, saved_user: User
) -> None:
    doc = Document.create(
        user_id=saved_user.id,
        filename="jan.pdf",
        file_path="files/15-01/jan.pdf",
        file_hash="unique_hash_xyz",
    )
    await doc_repo.save(doc)
    found = await doc_repo.get_by_hash("unique_hash_xyz")
    assert found is not None and found.id == doc.id


async def test_document_list_by_user(
    doc_repo: DocumentRepository, saved_user: User
) -> None:
    for i in range(3):
        await doc_repo.save(
            Document.create(
                user_id=saved_user.id,
                filename=f"doc{i}.pdf",
                file_path=f"files/15-01/doc{i}.pdf",
                file_hash=f"hash{i}",
            )
        )
    docs = await doc_repo.list_by_user(saved_user.id)
    assert len(docs) == 3


async def test_document_update_status(
    doc_repo: DocumentRepository, saved_user: User
) -> None:
    doc = await doc_repo.save(
        Document.create(
            user_id=saved_user.id,
            filename="x.pdf",
            file_path="files/01-01/x.pdf",
            file_hash="hashx",
        )
    )
    doc.mark_processed()
    await doc_repo.update(doc)
    updated = await doc_repo.get_by_id(doc.id)
    assert updated is not None and updated.status == DocumentStatus.PROCESSED


# ── Transaction ──────────────────────────────────────────────────────────────


async def test_transaction_save_and_retrieve(
    doc_repo: DocumentRepository,
    tx_repo: TransactionRepository,
    saved_user: User,
) -> None:
    doc = await doc_repo.save(
        Document.create(
            user_id=saved_user.id,
            filename="s.pdf",
            file_path="files/01-01/s.pdf",
            file_hash="hashs",
        )
    )
    tx = Transaction.create(
        user_id=saved_user.id,
        document_id=doc.id,
        date=date(2024, 1, 15),
        description="Supermarket",
        amount=Decimal("42.50"),
        transaction_type=TransactionType.DEBIT,
        category=TransactionCategory.GROCERIES,
    )
    saved = await tx_repo.save(tx)
    found = await tx_repo.get_by_id(saved.id)
    assert found is not None and found.amount == Decimal("42.50")


async def test_transaction_get_by_user_and_month(
    doc_repo: DocumentRepository,
    tx_repo: TransactionRepository,
    saved_user: User,
) -> None:
    doc = await doc_repo.save(
        Document.create(
            user_id=saved_user.id,
            filename="s2.pdf",
            file_path="files/01-01/s2.pdf",
            file_hash="hashs2",
        )
    )
    for day in [1, 15, 28]:
        await tx_repo.save(
            Transaction.create(
                user_id=saved_user.id,
                document_id=doc.id,
                date=date(2024, 1, day),
                description="tx",
                amount=Decimal("10"),
                transaction_type=TransactionType.DEBIT,
                category=TransactionCategory.GROCERIES,
            )
        )
    # Different month — should be excluded
    await tx_repo.save(
        Transaction.create(
            user_id=saved_user.id,
            document_id=doc.id,
            date=date(2024, 2, 1),
            description="other month",
            amount=Decimal("999"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.GROCERIES,
        )
    )
    results = await tx_repo.get_by_user_and_month(saved_user.id, 2024, 1)
    assert len(results) == 3


async def test_transaction_batch_save(
    doc_repo: DocumentRepository,
    tx_repo: TransactionRepository,
    saved_user: User,
) -> None:
    doc = await doc_repo.save(
        Document.create(
            user_id=saved_user.id,
            filename="batch.pdf",
            file_path="files/01-01/batch.pdf",
            file_hash="hashbatch",
        )
    )
    txs = [
        Transaction.create(
            user_id=saved_user.id,
            document_id=doc.id,
            date=date(2024, 1, i + 1),
            description=f"tx{i}",
            amount=Decimal("10"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.GROCERIES,
        )
        for i in range(5)
    ]
    saved = await tx_repo.save_batch(txs)
    assert len(saved) == 5
    stored = await tx_repo.get_by_document(doc.id)
    assert len(stored) == 5


# ── Account ──────────────────────────────────────────────────────────────────


async def test_account_save_and_list_by_user(
    account_repo: AccountRepository, saved_user: User
) -> None:
    await account_repo.save(
        Account.create(
            user_id=saved_user.id,
            name="Main Checking",
            account_type=AccountType.CHECKING,
            institution="Deutsche Bank",
        )
    )
    accounts = await account_repo.list_by_user(saved_user.id)
    assert len(accounts) == 1 and accounts[0].name == "Main Checking"


async def test_account_update(
    account_repo: AccountRepository, saved_user: User
) -> None:
    account = await account_repo.save(
        Account.create(
            user_id=saved_user.id,
            name="Savings",
            account_type=AccountType.SAVINGS,
        )
    )
    account.last_known_balance = Decimal("5000.00")
    await account_repo.update(account)
    updated = await account_repo.get_by_id(account.id)
    assert updated is not None and updated.last_known_balance == Decimal("5000.00")


# ── Insight ──────────────────────────────────────────────────────────────────


async def test_insight_save_and_retrieve(
    insight_repo: InsightRepository, saved_user: User
) -> None:
    insight = BudgetInsight.create(
        user_id=saved_user.id,
        year=2024,
        month=1,
        total_income=Decimal("3000"),
        total_expenses=Decimal("1800"),
        spending_breakdown=[
            SpendingBreakdown("groceries", Decimal("400"), 10, Decimal("22.22"))
        ],
        llm_summary="Great month.",
        llm_tips=["Save more.", "Invest."],
    )
    await insight_repo.save(insight)
    found = await insight_repo.get_by_user_and_month(saved_user.id, 2024, 1)
    assert found is not None and found.llm_summary == "Great month."


async def test_insight_upsert_overwrites(
    insight_repo: InsightRepository, saved_user: User
) -> None:
    def _make(summary: str) -> BudgetInsight:
        return BudgetInsight.create(
            user_id=saved_user.id,
            year=2024,
            month=1,
            total_income=Decimal("3000"),
            total_expenses=Decimal("1500"),
            spending_breakdown=[],
            llm_summary=summary,
            llm_tips=[],
        )

    await insight_repo.save(_make("First"))
    await insight_repo.save(_make("Updated"))
    found = await insight_repo.get_by_user_and_month(saved_user.id, 2024, 1)
    assert found is not None and found.llm_summary == "Updated"
    assert len(await insight_repo.list_by_user(saved_user.id)) == 1


async def test_insight_list_by_user(
    insight_repo: InsightRepository, saved_user: User
) -> None:
    for month in [1, 2, 3]:
        await insight_repo.save(
            BudgetInsight.create(
                user_id=saved_user.id,
                year=2024,
                month=month,
                total_income=Decimal("3000"),
                total_expenses=Decimal("1500"),
                spending_breakdown=[],
                llm_summary=f"Month {month}",
                llm_tips=[],
            )
        )
    results = await insight_repo.list_by_user(saved_user.id)
    assert len(results) == 3
