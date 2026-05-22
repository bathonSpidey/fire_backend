"""
Integration test for the N26 PDF parser.
Reads the real N26 statement via PyMuPDF and verifies extraction.

Run with:
    uv run pytest tests/integration/test_n26_reader.py -v -s
"""

from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest

from fire.infrastructure.llm.pdf_parsing.n26_parser import N26PdfParser

DATA_DIR = Path(__file__).parent / "data"
N26_PDF = DATA_DIR / "n26statement-2026-04.pdf"


@pytest.fixture
def n26_result():
    if not N26_PDF.exists():
        pytest.skip(f"N26 statement not found at {N26_PDF}")

    doc = pymupdf.open(str(N26_PDF))
    text = "\n".join(page.get_text() for page in doc)

    parser = N26PdfParser()
    lines = parser.filter_lines(text)
    transactions = parser.parse_lines(lines)
    return transactions


def test_n26_extracts_transactions(n26_result) -> None:
    transactions = n26_result

    print(f"\n{'=' * 60}")
    print(f"N26 extracted {len(transactions)} transactions")
    print(f"{'=' * 60}")
    for tx in transactions:
        sign = "+" if tx.transaction_type.value == "credit" else "-"
        print(f"  {tx.date}  {sign}€{tx.amount:<10}  {tx.description[:45]}")
    print(f"{'=' * 60}")

    assert len(transactions) > 0
    assert all(tx.amount > Decimal("0") for tx in transactions)
    assert all(tx.date is not None for tx in transactions)
