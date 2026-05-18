"""
Live tests against real documents and real APIs.
Excluded from the normal test run.

Run with:
    uv run pytest -m live -v -s
"""

import os
from decimal import Decimal

import pytest
from src.fire.config.settings import Settings
from src.fire.domain.entities.transaction import TransactionType
from src.fire.infrastructure.llm.gemini_document_parser import GeminiDocumentParser
from src.fire.infrastructure.llm.pdf_text_parser import PdfTextParser

pytestmark = pytest.mark.live


@pytest.fixture
def pdf_parser() -> PdfTextParser:
    return PdfTextParser()


@pytest.fixture
def gemini_parser() -> GeminiDocumentParser:

    s = Settings()  # reads .env automatically via pydantic-settings
    if not s.gemini_api_key:
        pytest.skip("GEMINI_API_KEY not set — skipping live receipt tests")
    return GeminiDocumentParser(api_key=s.gemini_api_key, model=s.gemini_model)


# ── PDF bank statement — rules-based, no API ─────────────────────────────────


async def test_bank_statement_extracts_transactions(
    pdf_parser: PdfTextParser,
    bank_statement_pdf: bytes,
) -> None:
    result = await pdf_parser.parse(bank_statement_pdf, mime_type="application/pdf")
    print(f"\nAccount:  {result.account_name} @ {result.account_institution}")
    print(f"Period:   {result.statement_period_start} → {result.statement_period_end}")
    print(f"Balance:  €{result.closing_balance}")
    print(f"Transactions: {len(result.transactions)}")
    for tx in result.transactions:
        sign = "+" if tx.transaction_type == TransactionType.CREDIT else "-"
        print(f"  {tx.date} | {tx.description:<45} | {sign}€{tx.amount:<10} | {tx.category}")
    assert len(result.transactions) > 0


async def test_bank_statement_amounts_are_positive(
    pdf_parser: PdfTextParser,
    bank_statement_pdf: bytes,
) -> None:
    result = await pdf_parser.parse(bank_statement_pdf, mime_type="application/pdf")
    for tx in result.transactions:
        assert tx.amount >= Decimal("0"), f"Negative: {tx.amount} in '{tx.description}'"


async def test_bank_statement_dates_are_valid(
    pdf_parser: PdfTextParser,
    bank_statement_pdf: bytes,
) -> None:
    result = await pdf_parser.parse(bank_statement_pdf, mime_type="application/pdf")
    for tx in result.transactions:
        assert tx.date is not None
        assert tx.date.year >= 2000


async def test_pdf_parser_available(pdf_parser: PdfTextParser) -> None:
    assert await pdf_parser.is_available()


# ── Kaufland receipt — Gemini vision ─────────────────────────────────────────


async def test_kaufland_small_extracts_transactions(
    gemini_parser: GeminiDocumentParser,
    kaufland_small: bytes,
) -> None:
    result = await gemini_parser.parse(kaufland_small, mime_type="image/png")
    print(f"\nStore: {result.account_name}  Total: €{result.closing_balance}")
    for tx in result.transactions:
        print(f"  {tx.date} | {tx.description:<35} | €{tx.amount}")
    assert len(result.transactions) > 0
    assert all(tx.amount > Decimal("0") for tx in result.transactions)


async def test_kaufland_small_all_debits(
    gemini_parser: GeminiDocumentParser,
    kaufland_small: bytes,
) -> None:
    result = await gemini_parser.parse(kaufland_small, mime_type="image/png")
    assert all(tx.transaction_type == TransactionType.DEBIT for tx in result.transactions)


async def test_kaufland_long_extracts_transactions(
    gemini_parser: GeminiDocumentParser,
    kaufland_long: bytes,
) -> None:
    result = await gemini_parser.parse(kaufland_long, mime_type="image/png")
    print(f"\nStore: {result.account_name}  Total: €{result.closing_balance}")
    for tx in result.transactions:
        print(f"  {tx.date} | {tx.description:<35} | €{tx.amount}")
    assert len(result.transactions) > 0


async def test_gemini_is_available(gemini_parser: GeminiDocumentParser) -> None:
    assert await gemini_parser.is_available()
