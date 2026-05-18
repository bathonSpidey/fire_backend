from decimal import Decimal

import pytest
from src.fire.domain.entities.transaction import TransactionCategory, TransactionType
from src.fire.infrastructure.llm.pdf_text_parser import _AMOUNT_RE, PdfTextParser


async def test_is_available() -> None:
    assert await PdfTextParser().is_available()


async def test_rejects_non_pdf_mime_type() -> None:
    parser = PdfTextParser()
    with pytest.raises(ValueError, match="only handles PDFs"):
        await parser.parse(b"fake", mime_type="image/png")


def test_amount_regex_matches_german_format() -> None:
    cases = [
        ("790,00", "790,00"),
        ("1.234,56", "1.234,56"),
        ("1.752,37", "1.752,37"),
        ("-250,00", "-250,00"),
    ]
    for text, expected in cases:
        match = _AMOUNT_RE.search(text)
        assert match, f"No match for: {text}"
        assert match.group() == expected


def test_amount_normalisation() -> None:
    cases = [
        ("790,00", Decimal("790.00")),
        ("1.234,56", Decimal("1234.56")),
        ("1.752,37", Decimal("1752.37")),
    ]
    for raw, expected in cases:
        normalized = raw.lstrip("-").replace(".", "").replace(",", ".")
        assert Decimal(normalized) == expected


def test_empty_pdf_returns_empty_transactions() -> None:
    parser = PdfTextParser()
    result = parser._parse_text("")
    assert result.transactions == []


def test_categorises_miete_as_housing() -> None:
    parser = PdfTextParser()
    assert parser._categorise("Wohngenossenschaft Miete und NK") == TransactionCategory.HOUSING


def test_categorises_gehalt_as_income() -> None:
    parser = PdfTextParser()
    assert parser._categorise("Lohn/Gehalt Abrechnung 4129-000212") == TransactionCategory.INCOME


def test_categorises_stadtwerke_as_utilities() -> None:
    parser = PdfTextParser()
    assert (
        parser._categorise("Stadtwerke Musterstadt Vertragsnummer") == TransactionCategory.UTILITIES
    )


def test_infers_credit_from_zahlungseingang() -> None:
    parser = PdfTextParser()
    assert parser._infer_type("Zahlungseingang Lohn/Gehalt") == TransactionType.CREDIT


def test_infers_credit_from_lohn_gehalt() -> None:
    parser = PdfTextParser()
    assert (
        parser._infer_type("Stadtwerke Musterstadt Lohn/Gehalt Abrechnung")
        == TransactionType.CREDIT
    )


def test_infers_credit_from_einzahlung() -> None:
    parser = PdfTextParser()
    assert parser._infer_type("SB-Einzahlung Gewerbepark GA 0731") == TransactionType.CREDIT


def test_infers_debit_from_lastschrift() -> None:
    parser = PdfTextParser()
    assert parser._infer_type("Lastschrift Mobilfunkgesellschaft") == TransactionType.DEBIT


def test_infers_debit_as_default() -> None:
    parser = PdfTextParser()
    assert parser._infer_type("Unknown transaction description") == TransactionType.DEBIT
