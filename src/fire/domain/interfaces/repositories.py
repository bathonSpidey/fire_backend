from abc import ABC, abstractmethod
from datetime import date
from uuid import UUID

from fire.domain.entities.account import Account
from fire.domain.entities.budget_insight import BudgetInsight
from fire.domain.entities.document import Document
from fire.domain.entities.transaction import Transaction, TransactionCategory


class IDocumentRepository(ABC):
    @abstractmethod
    async def save(self, document: Document) -> Document: ...

    @abstractmethod
    async def get_by_id(self, document_id: UUID) -> Document | None: ...

    @abstractmethod
    async def get_by_hash(self, file_hash: str) -> Document | None: ...

    @abstractmethod
    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Document]: ...

    @abstractmethod
    async def update(self, document: Document) -> Document: ...


class ITransactionRepository(ABC):
    @abstractmethod
    async def save(self, transaction: Transaction) -> Transaction: ...

    @abstractmethod
    async def save_batch(self, transactions: list[Transaction]) -> list[Transaction]: ...

    @abstractmethod
    async def get_by_id(self, transaction_id: UUID) -> Transaction | None: ...

    @abstractmethod
    async def get_by_document(self, document_id: UUID) -> list[Transaction]: ...

    @abstractmethod
    async def get_by_month(self, year: int, month: int) -> list[Transaction]: ...

    @abstractmethod
    async def get_by_category(
        self,
        category: TransactionCategory,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[Transaction]: ...


class IAccountRepository(ABC):
    @abstractmethod
    async def save(self, account: Account) -> Account: ...

    @abstractmethod
    async def get_by_id(self, account_id: UUID) -> Account | None: ...

    @abstractmethod
    async def list_active(self) -> list[Account]: ...

    @abstractmethod
    async def update(self, account: Account) -> Account: ...


class IInsightRepository(ABC):
    @abstractmethod
    async def save(self, insight: BudgetInsight) -> BudgetInsight: ...

    @abstractmethod
    async def get_by_month(self, year: int, month: int) -> BudgetInsight | None: ...

    @abstractmethod
    async def list_all(self, limit: int = 12) -> list[BudgetInsight]: ...
