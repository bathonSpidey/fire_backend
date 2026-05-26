from abc import ABC, abstractmethod
from datetime import date as Date
from uuid import UUID

from fire.domain.entities.account import Account
from fire.domain.entities.budget_insight import BudgetInsight
from fire.domain.entities.document import Document
from fire.domain.entities.transaction import Transaction, TransactionCategory
from fire.domain.entities.user import User


class IUserRepository(ABC):
    @abstractmethod
    async def save(self, user: User) -> User: ...

    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> User | None: ...

    @abstractmethod
    async def list_all(self) -> list[User]: ...


class IDocumentRepository(ABC):
    @abstractmethod
    async def save(self, document: Document) -> Document: ...

    @abstractmethod
    async def delete(self, document_id: UUID) -> None: ...

    @abstractmethod
    async def get_by_id(self, document_id: UUID) -> Document | None: ...

    @abstractmethod
    async def get_by_hash(self, file_hash: str) -> Document | None: ...

    @abstractmethod
    async def list_by_user(
        self, user_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[Document]: ...

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
    async def delete_by_document(self, document_id: UUID) -> int: ...

    @abstractmethod
    async def get_by_user_and_month(
        self, user_id: UUID, year: int, month: int
    ) -> list[Transaction]: ...

    @abstractmethod
    async def delete(self, transaction_id: UUID) -> None: ...

    @abstractmethod
    async def get_all_by_user(self, user_id: UUID) -> list[Transaction]: ...

    @abstractmethod
    async def get_by_transfer_document(self, transfer_document_id: UUID) -> list[Transaction]: ...

    @abstractmethod
    async def get_transfers_by_user(self, user_id: UUID) -> list[Transaction]: ...


    @abstractmethod
    async def get_by_parent(self, parent_transaction_id: UUID) -> list[Transaction]: ...

    @abstractmethod
    async def get_by_category(
        self,
        user_id: UUID,
        category: TransactionCategory,
        from_date: Date | None = None,
        to_date: Date | None = None,
    ) -> list[Transaction]: ...


class IAccountRepository(ABC):
    @abstractmethod
    async def save(self, account: Account) -> Account: ...

    @abstractmethod
    async def get_by_id(self, account_id: UUID) -> Account | None: ...

    @abstractmethod
    async def list_by_user(self, user_id: UUID) -> list[Account]: ...

    @abstractmethod
    async def update(self, account: Account) -> Account: ...


class IInsightRepository(ABC):
    @abstractmethod
    async def save(self, insight: BudgetInsight) -> BudgetInsight: ...

    @abstractmethod
    async def get_by_user_and_month(
        self, user_id: UUID, year: int, month: int
    ) -> BudgetInsight | None: ...

    @abstractmethod
    async def list_by_user(self, user_id: UUID, limit: int = 12) -> list[BudgetInsight]: ...
