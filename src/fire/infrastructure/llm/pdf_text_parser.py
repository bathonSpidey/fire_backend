"""
PDF bank statement parser — thin wrapper over pdf_parsing subpackage.

Routes to the correct bank-specific parser automatically:
  - N26 statements  → N26PdfParser
  - Everything else → SparkassePdfParser (generic German bank format)

This module keeps the existing import path stable.
"""

from fire.domain.interfaces.services import ExtractionResult, ILLMDocumentParser
from fire.infrastructure.llm.pdf_parsing.pdf_bank_parser_factory import PdfBankParserFactory

# Re-export for tests that import directly
from fire.infrastructure.llm.pdf_parsing.shared import (  # noqa: F401
    _AMOUNT_RE,
    CATEGORY_KEYWORDS,
)
from fire.infrastructure.llm.pdf_parsing.shared import (
    categorise as _categorise,
)
from fire.infrastructure.llm.pdf_parsing.shared import (
    infer_type as _infer_type,
)


class PdfTextParser(ILLMDocumentParser):
    """
    Parses bank statement PDFs using rules-based text extraction.
    No network calls — runs entirely locally and free.

    Automatically detects the bank format and routes to the
    appropriate parser implementation.
    """

    def __init__(self) -> None:
        self._factory = PdfBankParserFactory()

    async def parse(
        self,
        file_bytes: bytes,
        mime_type: str,
        account_name: str | None = None,
    ) -> ExtractionResult:
        if mime_type != "application/pdf":
            raise ValueError(
                f"PdfTextParser only handles PDFs, got: {mime_type}. "
                "Use a vision-based parser for image receipts."
            )
        return self._factory.parse(file_bytes, account_name=account_name)

    async def is_available(self) -> bool:
        try:
            import fitz  # noqa: F401

            return True
        except ImportError:
            return False

    # ── Kept for unit tests ────────────────────────────────────────────────
    # Tests import these methods directly — keep them as thin pass-throughs

    def _parse_text(self, text: str) -> ExtractionResult:
        from fire.infrastructure.llm.pdf_parsing.sparkasse_parser import SparkassePdfParser

        parser = SparkassePdfParser()
        lines = parser.filter_lines(text)
        transactions = parser.parse_lines(lines)
        return ExtractionResult(
            transactions=transactions,
            account_name=None,
            account_institution=None,
            statement_period_start=None,
            statement_period_end=None,
            closing_balance=None,
            raw_llm_response=text[:500],
        )

    @staticmethod
    def _categorise(description: str):
        from fire.infrastructure.llm.pdf_parsing.shared import categorise

        return categorise(description)

    @staticmethod
    def _infer_type(description: str):
        from fire.infrastructure.llm.pdf_parsing.shared import infer_type

        return infer_type(description)
