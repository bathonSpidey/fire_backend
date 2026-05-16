from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date as Date  # noqa: N812
from decimal import Decimal
from pathlib import Path

from fire.domain.entities.transaction import TransactionCategory, TransactionType


@dataclass
class ExtractedTransaction:
    """Raw data from LLM extraction — not yet a domain entity."""

    date: Date
    description: str
    amount: Decimal
    transaction_type: TransactionType
    category: TransactionCategory
    merchant: str | None = None


@dataclass
class ExtractionResult:
    """Full result of an LLM document parse."""

    transactions: list[ExtractedTransaction]
    account_name: str | None
    account_institution: str | None
    statement_period_start: Date | None
    statement_period_end: Date | None
    closing_balance: Decimal | None
    raw_llm_response: str


class ILLMDocumentParser(ABC):
    """Parses a raw file (PDF bytes or image bytes) into structured financial data."""

    @abstractmethod
    async def parse(self, file_bytes: bytes, mime_type: str) -> ExtractionResult: ...

    @abstractmethod
    async def is_available(self) -> bool: ...


class ILLMInsightGenerator(ABC):
    """Generates human-readable monthly insights from transaction summaries."""

    @abstractmethod
    async def generate_monthly_insight(
        self,
        year: int,
        month: int,
        total_income: Decimal,
        total_expenses: Decimal,
        category_totals: dict[str, Decimal],
    ) -> tuple[str, list[str]]:
        """Returns (summary_text, list_of_tips)."""
        ...

    @abstractmethod
    async def is_available(self) -> bool: ...


class IFileStorage(ABC):
    """
    Stores and retrieves raw uploaded files.

    Layout on disk:
        <root>/files/<DD-MM>/          ← one folder per calendar day
            statement_<hash>.pdf
            receipt_<hash>.png
        <root>/db/
            fire.db
    """

    @abstractmethod
    async def save(self, filename: str, content: bytes, upload_date: Date) -> Path:
        """
        Persist file under files/<DD-MM>/<filename> and return the full path.
        Callers pass upload_date so the folder is deterministic and testable.
        """
        ...

    @abstractmethod
    async def read(self, file_path: Path) -> bytes: ...

    @abstractmethod
    async def delete(self, file_path: Path) -> None: ...

    @abstractmethod
    async def compute_hash(self, content: bytes) -> str: ...

    @abstractmethod
    def daily_folder(self, upload_date: Date) -> Path:
        """Returns  <root>/files/<DD-MM>  without creating it."""
        ...
