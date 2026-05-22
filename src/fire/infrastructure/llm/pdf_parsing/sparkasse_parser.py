"""
Parser for Sparkasse (and generic German bank) statement PDFs.

Format characteristics:
  - Two amount columns: Betrag Soll EUR / Betrag Haben EUR
  - Debit in left column (negative or Soll), credit in right (Haben)
  - Date anchors each transaction row: DD.MM.YYYY
  - Description spans multiple lines after the date
"""

from datetime import date as Date
from decimal import Decimal, InvalidOperation

from fire.domain.entities.transaction import TransactionType
from fire.domain.interfaces.services import ExtractedTransaction, ExtractionResult
from fire.infrastructure.llm.pdf_parsing.shared import (
    _AMOUNT_RE,
    _DATE_RE,
    build_noise_re,
    categorise,
    infer_type,
    parse_date,
)

_NOISE_RE = build_noise_re([
    r"^nr\.\s+\d{2}/\d{4}",
    r"^kontostand\b",
    r"alter kontostand",
    r"neuer kontostand",
    r"dein alter kontostand",
    r"dein neuer kontostand",
    r"^konto\s+\d",
    r"^blz\b",
    r"ihre?\s+iban",
    r"^uebertrag\s+(von|auf)\s+seite",
])


class SparkassePdfParser:
    """
    Parses Sparkasse and generic German bank statement PDFs.
    Uses Soll/Haben column position to determine debit vs credit.
    """

    def parse_lines(self, lines: list[str]) -> list[ExtractedTransaction]:
        transactions: list[ExtractedTransaction] = []
        i = 0
        while i < len(lines):
            date = parse_date(lines[i])
            if date:
                desc_parts: list[str] = []
                amount: Decimal | None = None
                tx_type: TransactionType | None = None
                j = i + 1
                while j < len(lines) and j < i + 8:
                    amt, t = self._parse_amount_and_type(lines[j])
                    if amt is not None:
                        amount = amt
                        tx_type = t
                        break
                    if not _DATE_RE.match(lines[j]):
                        desc_parts.append(lines[j])
                    j += 1

                if amount is not None and amount > Decimal("0"):
                    description = " ".join(desc_parts).strip()
                    if description:
                        transactions.append(ExtractedTransaction(
                            date=date,
                            description=description,
                            amount=amount,
                            transaction_type=tx_type or infer_type(description),
                            category=categorise(description),
                            merchant=description.split()[0].title() if description else None,
                        ))
                    i = j + 1
                    continue
            i += 1
        return transactions

    @staticmethod
    def _parse_amount_and_type(
        line: str,
    ) -> tuple[Decimal | None, TransactionType | None]:
        match = _AMOUNT_RE.search(line)
        if not match:
            return None, None

        raw = match.group()
        is_negative = raw.startswith("-") or line.strip().endswith("-")
        normalized = raw.lstrip("+-").replace(".", "").replace(",", ".")

        try:
            amount = Decimal(normalized)
        except InvalidOperation:
            return None, None

        line_lower = line.lower()
        if "soll" in line_lower or is_negative:
            return amount, TransactionType.DEBIT
        if "haben" in line_lower:
            return amount, TransactionType.CREDIT

        all_matches = _AMOUNT_RE.findall(line)
        if len(all_matches) == 2:
            pos = match.start()
            tx_type = TransactionType.DEBIT if pos < len(line) // 2 else TransactionType.CREDIT
            return amount, tx_type

        return amount, None

    @staticmethod
    def filter_lines(text: str) -> list[str]:
        return [
            ln.strip()
            for ln in text.splitlines()
            if ln.strip() and not _NOISE_RE.search(ln.strip())
        ]