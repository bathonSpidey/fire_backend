"""
Claude-based parser for image receipts and invoices.
Calls the Anthropic Messages API directly via httpx.

API reference: https://docs.anthropic.com/en/api/messages
"""

import base64
import json
import re
from datetime import date as Date
from datetime import datetime
from decimal import Decimal, InvalidOperation

import httpx

from src.fire.domain.entities.transaction import TransactionCategory, TransactionType
from src.fire.domain.interfaces.services import (
    ExtractedTransaction,
    ExtractionResult,
    ILLMDocumentParser,
)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

_PROMPT = """You are a financial data extraction API.
Extract every line item from this receipt or invoice image.

Rules:
- Every purchasable item is a separate transaction
- Skip discount/Rabatt lines and lines with negative amounts
- Dates in DD.MM.YYYY format: convert to YYYY-MM-DD
- Amounts with comma decimal (2,49) → convert to 2.49
- All receipt items are debit
- Use the receipt date for all items
- Merchant is the store name at the top of the receipt

Output ONLY valid JSON — no explanation, no markdown:
{
  "account_name": "store name or null",
  "account_institution": null,
  "statement_period_start": null,
  "statement_period_end": null,
  "closing_balance": "total paid as decimal or null",
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "description": "item name exactly as printed",
      "amount": "positive decimal e.g. 2.49",
      "transaction_type": "debit",
      "category": "groceries|dining|transport|housing|utilities|healthcare|entertainment|shopping|income|investment|savings|transfer|other",
      "merchant": "store name or null"
    }
  ]
}"""

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%y",
]


class ClaudeDocumentParser(ILLMDocumentParser):
    """
    Parses image receipts using the Anthropic Messages API via httpx.

    No Anthropic SDK dependency — calls the REST endpoint directly.
    Only handles images. PDFs → PdfTextParser.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-opus-4-5",
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to your .env file: ANTHROPIC_API_KEY=sk-ant-..."
            )
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    async def parse(self, file_bytes: bytes, mime_type: str) -> ExtractionResult:
        b64 = base64.standard_b64encode(file_bytes).decode()

        payload = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        }

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(_ANTHROPIC_URL, json=payload, headers=headers)
            response.raise_for_status()

        raw_text = response.json()["content"][0]["text"]
        return self._parse_response(raw_text)

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": _ANTHROPIC_VERSION,
                    },
                )
                return r.status_code == 200
        except httpx.ConnectError:
            return False

    # ── Response parsing — identical to GeminiDocumentParser ──────────────

    def _parse_response(self, raw_text: str) -> ExtractionResult:
        clean = self._extract_json(raw_text)
        data = json.loads(clean)
        transactions = [
            self._parse_transaction(tx) for tx in data.get("transactions", []) if self._is_valid(tx)
        ]
        return ExtractionResult(
            transactions=transactions,
            account_name=self._none_if_null(data.get("account_name")),
            account_institution=self._none_if_null(data.get("account_institution")),
            statement_period_start=self._parse_date(data.get("statement_period_start")),
            statement_period_end=self._parse_date(data.get("statement_period_end")),
            closing_balance=self._parse_decimal(data.get("closing_balance")),
            raw_llm_response=raw_text,
        )

    def _parse_transaction(self, tx: dict) -> ExtractedTransaction:  # type: ignore[type-arg]
        return ExtractedTransaction(
            date=self._parse_date(tx["date"]) or Date.today(),
            description=tx.get("description", ""),
            amount=Decimal(self._clean_amount(tx["amount"])),
            transaction_type=TransactionType(tx.get("transaction_type", "debit")),
            category=self._safe_category(tx.get("category", "other")),
            merchant=self._none_if_null(tx.get("merchant")),
        )

    @staticmethod
    def _is_valid(tx: dict) -> bool:  # type: ignore[type-arg]
        return bool(tx.get("date")) and bool(tx.get("amount"))

    @staticmethod
    def _clean_amount(value: str | float | int) -> str:
        cleaned = str(value).strip()
        for token in ["EUR", "USD", "GBP", "€", "$", "£", "\u00a0", " "]:
            cleaned = cleaned.replace(token, "")
        cleaned = cleaned.lstrip("-+")
        if "," in cleaned and "." in cleaned:
            if cleaned.index(".") < cleaned.index(","):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        cleaned = re.sub(r"[^\d.]", "", cleaned)
        parts = cleaned.split(".")
        if len(parts) > 2:
            cleaned = "".join(parts[:-1]) + "." + parts[-1]
        return cleaned or "0"

    @staticmethod
    def _extract_json(text: str) -> str:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            return match.group(1).strip()
        start, end = text.find("{"), text.rfind("}") + 1
        if start != -1 and end > start:
            return text[start:end]
        return text.strip()

    @staticmethod
    def _safe_category(value: str) -> TransactionCategory:
        try:
            return TransactionCategory(value.lower())
        except ValueError:
            return TransactionCategory.OTHER

    @staticmethod
    def _none_if_null(value: str | None) -> str | None:
        if value is None or str(value).lower() in ("null", "none", ""):
            return None
        return value

    @staticmethod
    def _parse_date(value: str | None) -> Date | None:
        if not value or str(value).lower() in ("null", "none"):
            return None
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_decimal(value: str | None) -> Decimal | None:
        if not value or str(value).lower() in ("null", "none"):
            return None
        try:
            return Decimal(str(value).replace(",", "."))
        except InvalidOperation:
            return None
