import base64
import io
import json
import re
from datetime import date as Date
from datetime import datetime
from decimal import Decimal, InvalidOperation

import httpx
from PIL import Image

from src.fire.domain.entities.transaction import TransactionCategory, TransactionType
from src.fire.domain.interfaces.services import (
    ExtractedTransaction,
    ExtractionResult,
    ILLMDocumentParser,
)

# ── Prompts ───────────────────────────────────────────────────────────────────

_TEXT_PROMPT = (
    "Extract all transactions from this German bank statement text.\n\n"
    "Rules:\n"
    "- Dates in DD.MM.YYYY format: convert to YYYY-MM-DD\n"
    "- Amounts: remove dots used as thousand separators, use period as decimal "
    "e.g. 1.752,37 becomes 1752.37\n"
    "- Debit (money leaving): Lastschrift, Kartenzahlung, Dauerauftrag, Geldautomat\n"
    "- Credit (money entering): Zahlungseingang, Gutschrift, Einzahlung, SB-Einzahlung\n"
    "- Amounts are always POSITIVE — transaction_type shows direction\n"
    "- Skip address lines and legal text — only extract transaction rows\n\n"
    "Output ONLY this JSON, no explanation, no markdown:\n"
    "{\n"
    '  "account_name": "account holder name or null",\n'
    '  "account_institution": "bank name or null",\n'
    '  "statement_period_start": "YYYY-MM-DD or null",\n'
    '  "statement_period_end": "YYYY-MM-DD or null",\n'
    '  "closing_balance": "final Kontostand as positive decimal or null",\n'
    '  "transactions": [\n'
    "    {\n"
    '      "date": "YYYY-MM-DD",\n'
    '      "description": "transaction description",\n'
    '      "amount": "positive decimal e.g. 790.00",\n'
    '      "transaction_type": "debit or credit",\n'
    '      "category": "groceries|dining|transport|housing|utilities|healthcare|'
    'entertainment|shopping|income|investment|savings|transfer|other",\n'
    '      "merchant": "payee name or null"\n'
    "    }\n"
    "  ]\n"
    "}"
)

_IMAGE_PROMPT = (
    "Extract every line item from this receipt image.\n\n"
    "Rules:\n"
    "- Every purchasable item is a separate transaction\n"
    "- Skip discount/Rabatt lines (negative amounts)\n"
    "- Dates in DD.MM.YYYY format: convert to YYYY-MM-DD\n"
    "- Amounts with comma decimal e.g. 2,49 become 2.49\n"
    "- All receipt items are debit\n"
    "- Use the receipt date for all items\n"
    "- Merchant is the store name at the top\n\n"
    "Output ONLY this JSON, no explanation, no markdown:\n"
    "{\n"
    '  "account_name": "store name or null",\n'
    '  "account_institution": null,\n'
    '  "statement_period_start": null,\n'
    '  "statement_period_end": null,\n'
    '  "closing_balance": "total paid as decimal or null",\n'
    '  "transactions": [\n'
    "    {\n"
    '      "date": "YYYY-MM-DD",\n'
    '      "description": "item name exactly as printed",\n'
    '      "amount": "positive decimal e.g. 2.49",\n'
    '      "transaction_type": "debit",\n'
    '      "category": "groceries",\n'
    '      "merchant": "store name or null"\n'
    "    }\n"
    "  ]\n"
    "}"
)

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%d.%m.%y",
    "%m/%d/%y",
]


class OllamaDocumentParser(ILLMDocumentParser):
    """
    Two-track document parser:
    - PDFs with selectable text  → extract text → send as text prompt to qwen3
    - Image receipts (PNG/JPEG)  → normalise to JPEG → vision prompt to gemma4
    """

    _MAX_WIDTH = 1024

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        vision_model: str = "gemma4:e2b",
        text_model: str = "qwen3:14b-q4_K_M",
        timeout: float = 180.0,
    ) -> None:
        self._base_url = base_url
        self._vision_model = vision_model
        self._text_model = text_model
        self._timeout = timeout

    async def parse(self, file_bytes: bytes, mime_type: str) -> ExtractionResult:
        if mime_type == "application/pdf":
            return await self._parse_pdf(file_bytes)
        return await self._parse_image(file_bytes)

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self._base_url}/api/tags")
                return r.status_code == 200
        except httpx.ConnectError:
            return False

    # ── PDF track ─────────────────────────────────────────────────────────────

    async def _parse_pdf(self, pdf_bytes: bytes) -> ExtractionResult:
        text = self._extract_pdf_text(pdf_bytes)
        if not text.strip():
            jpeg = self._pdf_to_jpeg(pdf_bytes)
            return await self._call_vision(jpeg, _IMAGE_PROMPT)
        return await self._call_text(text)

    @staticmethod
    def _extract_pdf_text(pdf_bytes: bytes) -> str:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)

    @staticmethod
    def _pdf_to_jpeg(pdf_bytes: bytes) -> bytes:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pixmap = doc[0].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        return pixmap.tobytes("jpeg")

    async def _call_text(self, text: str) -> ExtractionResult:
        payload = {
            "model": self._text_model,
            "messages": [
                {"role": "user", "content": f"{_TEXT_PROMPT}\n\nBANK STATEMENT TEXT:\n{text}"},
                # Priming the assistant with { forces the model to continue in JSON
                {"role": "assistant", "content": "{"},
            ],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(f"{self._base_url}/api/chat", json=payload)
            r.raise_for_status()
        # Re-attach the { we used to prime
        raw = "{" + r.json()["message"]["content"]
        return self._parse_response(raw)

    # ── Image track ───────────────────────────────────────────────────────────

    async def _parse_image(self, image_bytes: bytes) -> ExtractionResult:
        jpeg = self._normalise_to_jpeg(image_bytes)
        return await self._call_vision(jpeg, _IMAGE_PROMPT)

    async def _call_vision(self, jpeg_bytes: bytes, prompt: str) -> ExtractionResult:
        b64 = base64.b64encode(jpeg_bytes).decode()
        payload = {
            "model": self._vision_model,
            "messages": [
                {"role": "user", "content": prompt, "images": [b64]},
            ],
            "stream": False,
            "format": "json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(f"{self._base_url}/api/chat", json=payload)
            r.raise_for_status()
        return self._parse_response(r.json()["message"]["content"])

    def _normalise_to_jpeg(self, image_bytes: bytes) -> bytes:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        if img.width > self._MAX_WIDTH:
            ratio = self._MAX_WIDTH / img.width
            img = img.resize((self._MAX_WIDTH, int(img.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    # ── Response parsing ──────────────────────────────────────────────────────

    def _parse_response(self, raw_text: str) -> ExtractionResult:
        clean = self._extract_json(raw_text)
        data = json.loads(clean)
        transactions = [
            self._parse_transaction(tx)
            for tx in data.get("transactions", [])
            if self._is_valid_transaction(tx)
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
    def _is_valid_transaction(tx: dict) -> bool:  # type: ignore[type-arg]
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