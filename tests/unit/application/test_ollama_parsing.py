"""
Tests for the Ollama adapter's parsing logic only.
No real Ollama connection — we test _parse_response and helpers directly.
Real Ollama connectivity is verified manually or in a separate smoke test.
"""

import json
from datetime import date
from decimal import Decimal

import pytest
from src.fire.domain.entities.transaction import TransactionCategory, TransactionType
from src.fire.infrastructure.llm.ollama_document_parser import OllamaDocumentParser
from src.fire.infrastructure.llm.ollama_insight_generator import OllamaInsightGenerator


@pytest.fixture
def parser() -> OllamaDocumentParser:
    return OllamaDocumentParser()


@pytest.fixture
def generator() -> OllamaInsightGenerator:
    return OllamaInsightGenerator()


# ── OllamaDocumentParser ─────────────────────────────────────────────────────


def test_parser_extracts_transactions(parser: OllamaDocumentParser) -> None:
    raw = json.dumps(
        {
            "account_name": "Main Checking",
            "account_institution": "Deutsche Bank",
            "statement_period_start": "2024-01-01",
            "statement_period_end": "2024-01-31",
            "closing_balance": "1500.00",
            "transactions": [
                {
                    "date": "2024-01-15",
                    "description": "Lidl Supermarket",
                    "amount": "42.50",
                    "transaction_type": "debit",
                    "category": "groceries",
                    "merchant": "Lidl",
                }
            ],
        }
    )
    result = parser._parse_response(raw)
    assert len(result.transactions) == 1
    assert result.transactions[0].amount == Decimal("42.50")
    assert result.transactions[0].category == TransactionCategory.GROCERIES


def test_parser_strips_markdown_fences(parser: OllamaDocumentParser) -> None:
    raw = '```json\n{"transactions": [], "account_name": null, "account_institution": null, "statement_period_start": null, "statement_period_end": null, "closing_balance": null}\n```'
    result = parser._parse_response(raw)
    assert result.transactions == []


def test_parser_handles_unknown_category(parser: OllamaDocumentParser) -> None:
    raw = json.dumps(
        {
            "transactions": [
                {
                    "date": "2024-01-01",
                    "description": "Mystery charge",
                    "amount": "9.99",
                    "transaction_type": "debit",
                    "category": "completely_unknown_category",
                    "merchant": None,
                }
            ],
            "account_name": None,
            "account_institution": None,
            "statement_period_start": None,
            "statement_period_end": None,
            "closing_balance": None,
        }
    )
    result = parser._parse_response(raw)
    assert result.transactions[0].category == TransactionCategory.OTHER


def test_parser_handles_null_dates(parser: OllamaDocumentParser) -> None:
    raw = json.dumps(
        {
            "transactions": [],
            "account_name": None,
            "account_institution": None,
            "statement_period_start": None,
            "statement_period_end": None,
            "closing_balance": None,
        }
    )
    result = parser._parse_response(raw)
    assert result.statement_period_start is None
    assert result.statement_period_end is None


def test_parser_parses_closing_balance(parser: OllamaDocumentParser) -> None:
    raw = json.dumps(
        {
            "transactions": [],
            "account_name": None,
            "account_institution": None,
            "statement_period_start": None,
            "statement_period_end": None,
            "closing_balance": "2345.67",
        }
    )
    result = parser._parse_response(raw)
    assert result.closing_balance == Decimal("2345.67")


def test_parser_sets_credit_transaction_type(parser: OllamaDocumentParser) -> None:
    raw = json.dumps(
        {
            "transactions": [
                {
                    "date": "2024-01-01",
                    "description": "Salary",
                    "amount": "3000.00",
                    "transaction_type": "credit",
                    "category": "income",
                    "merchant": None,
                }
            ],
            "account_name": None,
            "account_institution": None,
            "statement_period_start": None,
            "statement_period_end": None,
            "closing_balance": None,
        }
    )
    result = parser._parse_response(raw)
    assert result.transactions[0].transaction_type == TransactionType.CREDIT


# ── OllamaInsightGenerator ───────────────────────────────────────────────────


def test_insight_generator_parses_valid_response(generator: OllamaInsightGenerator) -> None:
    raw = json.dumps(
        {
            "summary": "Good month overall.",
            "tips": ["Save more.", "Cut dining.", "Invest surplus."],
        }
    )
    summary, tips = generator._parse_response(raw)
    assert summary == "Good month overall."
    assert len(tips) == 3


def test_insight_generator_falls_back_on_bad_json(generator: OllamaInsightGenerator) -> None:
    raw = "This is not JSON at all, just plain text from the model."
    summary, tips = generator._parse_response(raw)
    assert len(summary) > 0
    assert tips == []


def test_insight_generator_caps_tips_at_five(generator: OllamaInsightGenerator) -> None:
    raw = json.dumps(
        {
            "summary": "Fine.",
            "tips": ["t1", "t2", "t3", "t4", "t5", "t6", "t7"],
        }
    )
    _, tips = generator._parse_response(raw)
    assert len(tips) <= 5
