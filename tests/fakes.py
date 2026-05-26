"""
Fake implementations of all domain interfaces.
Hand-rolled, no mocking library — Uncle Bob style.
"""

import hashlib
from datetime import date as Date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fire.domain.entities.account import Account
from fire.domain.entities.budget_insight import BudgetInsight
from fire.domain.entities.document import Document
from fire.domain.entities.transaction import Transaction, TransactionCategory
from fire.domain.entities.user import User
from fire.domain.interfaces.repositories import (
    IAccountRepository,
    IDocumentRepository,
    IInsightRepository,
    ITransactionRepository,
    IUserRepository,
)
from fire.domain.interfaces.services import (
    ExtractionResult,
    IFileStorage,
    ILLMDocumentParser,
    ILLMInsightGenerator,
)


class FakeUserRepository(IUserRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, User] = {}

    async def save(self, user: User) -> User:
        self._store[user.id] = user
        return user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._store.get(user_id)

    async def list_all(self) -> list[User]:
        return list(self._store.values())


class FakeDocumentRepository(IDocumentRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, Document] = {}

    async def save(self, document: Document) -> Document:
        self._store[document.id] = document
        return document

    async def get_by_id(self, document_id: UUID) -> Document | None:
        return self._store.get(document_id)

    async def get_by_hash(self, file_hash: str) -> Document | None:
        return next((d for d in self._store.values() if d.file_hash == file_hash), None)

    async def list_by_user(self, user_id: UUID, limit: int = 50, offset: int = 0) -> list[Document]:
        results = [d for d in self._store.values() if d.user_id == user_id]
        return results[offset : offset + limit]

    async def delete(self, document_id: UUID) -> None:
        self._store.pop(document_id, None)

    async def update(self, document: Document) -> Document:
        self._store[document.id] = document
        return document


class FakeTransactionRepository(ITransactionRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, Transaction] = {}

    async def save(self, transaction: Transaction) -> Transaction:
        self._store[transaction.id] = transaction
        return transaction

    async def save_batch(self, transactions: list[Transaction]) -> list[Transaction]:
        for t in transactions:
            self._store[t.id] = t
        return transactions

    async def get_by_id(self, transaction_id: UUID) -> Transaction | None:
        return self._store.get(transaction_id)

    async def get_by_document(self, document_id: UUID) -> list[Transaction]:
        return [t for t in self._store.values() if t.document_id == document_id]

    async def delete_by_document(self, document_id: UUID) -> int:
        keys = [k for k, t in self._store.items() if t.document_id == document_id]
        for k in keys:
            del self._store[k]
        return len(keys)

    async def get_by_user_and_month(
        self, user_id: UUID, year: int, month: int
    ) -> list[Transaction]:
        return [
            t
            for t in self._store.values()
            if t.user_id == user_id and t.date.year == year and t.date.month == month
        ]

    async def get_by_transfer_document(self, transfer_document_id: UUID) -> list[Transaction]:
        return [t for t in self._store.values() if t.document_id == transfer_document_id]

    async def get_transfers_by_user(self, user_id: UUID) -> list[Transaction]:
        return [
            t
            for t in self._store.values()
            if t.user_id == user_id and t.transaction_type.value == "transfer"
        ]

    async def get_by_parent(self, parent_transaction_id: UUID) -> list[Transaction]:
        return [t for t in self._store.values() if t.parent_transaction_id == parent_transaction_id]

    async def delete(self, transaction_id: UUID) -> None:
        self._store.pop(transaction_id, None)

    async def get_all_by_user(self, user_id: UUID) -> list[Transaction]:
        return [t for t in self._store.values() if t.user_id == user_id]

    async def get_by_category(
        self,
        user_id: UUID,
        category: TransactionCategory,
        from_date: Date | None = None,
        to_date: Date | None = None,
    ) -> list[Transaction]:
        results = [
            t for t in self._store.values() if t.user_id == user_id and t.category == category
        ]
        if from_date:
            results = [t for t in results if t.date >= from_date]
        if to_date:
            results = [t for t in results if t.date <= to_date]
        return results


class FakeAccountRepository(IAccountRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, Account] = {}

    async def save(self, account: Account) -> Account:
        self._store[account.id] = account
        return account

    async def get_by_id(self, account_id: UUID) -> Account | None:
        return self._store.get(account_id)

    async def list_by_user(self, user_id: UUID) -> list[Account]:
        return [a for a in self._store.values() if a.user_id == user_id and a.is_active]

    async def update(self, account: Account) -> Account:
        self._store[account.id] = account
        return account


class FakeInsightRepository(IInsightRepository):
    def __init__(self) -> None:
        self._store: dict[tuple[UUID, int, int], BudgetInsight] = {}

    async def save(self, insight: BudgetInsight) -> BudgetInsight:
        self._store[(insight.user_id, insight.year, insight.month)] = insight
        return insight

    async def get_by_user_and_month(
        self, user_id: UUID, year: int, month: int
    ) -> BudgetInsight | None:
        return self._store.get((user_id, year, month))

    async def list_by_user(self, user_id: UUID, limit: int = 12) -> list[BudgetInsight]:
        results = [i for i in self._store.values() if i.user_id == user_id]
        return results[-limit:]


class FakeFileStorage(IFileStorage):
    def __init__(self) -> None:
        self._store: dict[Path, bytes] = {}

    async def save(self, filename: str, content: bytes, upload_date: Date) -> Path:
        path = self.daily_folder(upload_date) / filename
        self._store[path] = content
        return path

    async def read(self, file_path: Path) -> bytes:
        if file_path not in self._store:
            raise FileNotFoundError(file_path)
        return self._store[file_path]

    async def delete(self, file_path: Path) -> None:
        self._store.pop(file_path, None)

    async def compute_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def daily_folder(self, upload_date: Date) -> Path:
        return Path("files") / upload_date.strftime("%d-%m")


class FakeLLMDocumentParser(ILLMDocumentParser):
    def __init__(self, result: ExtractionResult | None = None) -> None:
        self.result = result
        self.call_count = 0
        self.available = True

    async def parse(self, file_bytes: bytes, mime_type: str) -> ExtractionResult:
        self.call_count += 1
        if self.result is None:
            raise RuntimeError("FakeLLMDocumentParser.result not set")
        return self.result

    async def is_available(self) -> bool:
        return self.available


class FakeLLMInsightGenerator(ILLMInsightGenerator):
    def __init__(self, summary: str = "Test summary.", tips: list[str] | None = None) -> None:
        self.summary = summary
        self.tips = tips or ["Tip one.", "Tip two."]
        self.call_count = 0
        self.available = True

    async def generate_monthly_insight(
        self,
        year: int,
        month: int,
        total_income: Decimal,
        total_expenses: Decimal,
        category_totals: dict[str, Decimal],
    ) -> tuple[str, list[str]]:
        self.call_count += 1
        return self.summary, self.tips

    async def is_available(self) -> bool:
        return self.available
