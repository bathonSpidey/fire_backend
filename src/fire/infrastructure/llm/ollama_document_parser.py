import base64
import json
import re
from datetime import date as Date
from decimal import Decimal, InvalidOperation

import httpx

from fire.domain.interfaces.services import (
    ExtractedTransaction,
    ExtractionResult,
    ILLMDocumentParser,
)
from src.fire.domain.entities.transaction import TransactionCategory, TransactionType

_PARSE_PROMPT = """
You are a financial data extraction assistant.
Analyze this financial document (bank statement, investment statement, or receipt)
and extract all transactions.

Respond ONLY with a valid JSON object — no explanation, no markdown, no code fences.

JSON format:
{
  "account_name": "string or null",
  "account_institution": "string or null",
  "statement_period_start": "YYYY-MM-DD or null",
  "statement_period_end": "YYYY-MM-DD or null",
  "closing_balance": "decimal string or null",
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "description": "string",
      "amount": "decimal string, always positive",
      "transaction_type": "debit or credit",
      "category": "one of: groceries, dining, transport, housing, utilities, healthcare, entertainment, shopping, income, investment, savings, transfer, other",
      "merchant": "string or null"
    }
  ]
}
"""


class OllamaDocumentParser(ILLMDocumentParser):
    """
    Calls the local Ollama vision model (llava) to parse financial documents.
    Requires Ollama running on localhost with llava pulled.

    Recommended model for 12GB VRAM: llava:13b
    Fallback for less VRAM:          llava:7b
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llava:13b",
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._timeout = timeout

    async def parse(self, file_bytes: bytes, mime_type: str) -> ExtractionResult:
        encoded = base64.b64encode(file_bytes).decode("utf-8")

        payload = {
            "model": self._model,
            "prompt": _PARSE_PROMPT,
            "images": [encoded],
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}/api/generate", json=payload)
            response.raise_for_status()

        raw_text = response.json()["response"]
        return self._parse_response(raw_text)

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                return response.status_code == 200
        except httpx.ConnectError:
            return False

    def _parse_response(self, raw_text: str) -> ExtractionResult:
        clean = self._extract_json(raw_text)
        data = json.loads(clean)

        transactions = [self._parse_transaction(tx) for tx in data.get("transactions", [])]

        return ExtractionResult(
            transactions=transactions,
            account_name=data.get("account_name"),
            account_institution=data.get("account_institution"),
            statement_period_start=self._parse_date(data.get("statement_period_start")),
            statement_period_end=self._parse_date(data.get("statement_period_end")),
            closing_balance=self._parse_decimal(data.get("closing_balance")),
            raw_llm_response=raw_text,
        )

    def _parse_transaction(self, tx: dict) -> ExtractedTransaction:  # type: ignore[type-arg]
        return ExtractedTransaction(
            date=Date.fromisoformat(tx["date"]),
            description=tx.get("description", ""),
            amount=Decimal(str(tx["amount"])),
            transaction_type=TransactionType(tx.get("transaction_type", "debit")),
            category=self._safe_category(tx.get("category", "other")),
            merchant=tx.get("merchant"),
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown fences if the model wraps output in ```json ... ```."""
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            return match.group(1).strip()
        # Find the first { ... } block as fallback
        start = text.find("{")
        end = text.rfind("}") + 1
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
    def _parse_date(value: str | None) -> Date | None:
        if not value:
            return None
        try:
            return Date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _parse_decimal(value: str | None) -> Decimal | None:
        if not value:
            return None
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
