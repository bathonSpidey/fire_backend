"""
Parser for N26 bank statement PDFs.

N26 format characteristics:
  - Three columns: Description | Booking Date | Amount
  - Amount always has explicit +/- prefix: +5,00€ or -4,90€
  - Credits are incoming transfers or refunds (positive)
  - Debits are purchases, fees, outgoing transfers (negative)
  - IBAN lines follow each transaction description
  - "Value Date DD.MM.YYYY" appears on its own line — noise
  - "Sent from N26" appears as a sub-line — noise
  - Last page has account holder address info — noise

N26 row structure in extracted text:
  Damiao Luis Sebastiao Dos Santos    ← description (may span lines)
  IBAN: BE96...                       ← noise — skip
  Value Date 24.10.2024               ← noise — skip
  24.10.2024                          ← booking date (anchor)
  +5,00€                              ← amount with sign
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

_N26_NOISE_RE = build_noise_re([
    r"^value\s+date",
    r"^booking\s+date",
    r"^amount$",
    r"^sent\s+from\s+n26",
    r"^issued\s+on",
    r"^issued$",
    r"^\d+\s*/\s*\d+$",
    r"^rua\s+",
    r"^rue\s+",
    r"kontostand",
    r"^n26\s+business\s+smart",  # subscription line
    r"^n26\s+smart",
    r"dein\s+(alter|neuer)\s+kontostand",
])


class N26PdfParser:
    """
    Parses N26 bank statement PDFs.

    N26 uses explicit +/- on every amount so credit/debit detection
    is unambiguous — no column-position inference needed.
    """

    def parse_lines(self, lines: list[str]) -> list[ExtractedTransaction]:
        transactions: list[ExtractedTransaction] = []
        i = 0
        while i < len(lines):
            # N26 row: date anchor followed closely by a signed amount
            date = parse_date(lines[i])
            if date:
                # Look ahead for amount (within 3 lines)
                amount: Decimal | None = None
                tx_type: TransactionType | None = None
                for k in range(i + 1, min(i + 4, len(lines))):
                    amt, t = self._parse_n26_amount(lines[k])
                    if amt is not None:
                        amount = amt
                        tx_type = t
                        # Description is BEFORE the date anchor in N26 layout
                        # Collect lines before i going back up to 3 lines
                        desc_lines = []
                        for back in range(max(0, i - 4), i):
                            candidate = lines[back]
                            if (not _DATE_RE.match(candidate) and
                                    not _N26_NOISE_RE.search(candidate) and
                                    not _AMOUNT_RE.search(candidate)):
                                desc_lines.append(candidate)
                        description = " ".join(desc_lines).strip()
                        if not description:
                            description = "N26 transaction"
                        if amount > Decimal("0"):
                            transactions.append(ExtractedTransaction(
                                date=date,
                                description=description,
                                amount=amount,
                                transaction_type=tx_type or infer_type(description),
                                category=categorise(description),
                                merchant=description.split()[0].title() if description else None,
                            ))
                        i = k + 1
                        break
                else:
                    i += 1
                    continue
                continue
            i += 1
        return transactions

    @staticmethod
    def _parse_n26_amount(
        line: str,
    ) -> tuple[Decimal | None, TransactionType | None]:
        """
        N26 amounts always have explicit sign: +5,00 or -4,90
        May be followed by € symbol.
        """
        # Strip currency symbols
        cleaned = line.strip().replace("€", "").replace("EUR", "").strip()
        match = _AMOUNT_RE.match(cleaned)
        if not match:
            return None, None

        raw = match.group()
        if not (raw.startswith("+") or raw.startswith("-")):
            return None, None  # N26 always has explicit sign — skip ambiguous amounts

        is_positive = raw.startswith("+")
        normalized = raw.lstrip("+-").replace(".", "").replace(",", ".")

        try:
            amount = Decimal(normalized)
        except InvalidOperation:
            return None, None

        tx_type = TransactionType.CREDIT if is_positive else TransactionType.DEBIT
        return amount, tx_type

    @staticmethod
    def filter_lines(text: str) -> list[str]:
        return [
            ln.strip()
            for ln in text.splitlines()
            if ln.strip() and not _N26_NOISE_RE.search(ln.strip())
        ]

    @staticmethod
    def detect(text: str) -> bool:
        """Returns True if this PDF looks like an N26 statement."""
        lower = text[:2000].lower()
        return "n26" in lower and ("booking date" in lower or "value date" in lower)