"""
Rules-based parser for German bank statement PDFs.
Extracts text via PyMuPDF then applies regex patterns to find transactions.

Supports common German bank formats:
  - Sparkasse (Kontoauszug)
  - ING (Umsatzanzeige)
  - DKB (Kontoauszug)
  - Generic fallback for other formats

No API calls, no LLM, no network. Completely local and free.
"""

import re
from datetime import date as Date
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fire.domain.entities.transaction import TransactionCategory, TransactionType
from fire.domain.interfaces.services import (
    ExtractedTransaction,
    ExtractionResult,
    ILLMDocumentParser,
)

# ── Noise patterns — lines to skip entirely ──────────────────────────────────
# These are PDF headers, footers, navigation text, and section labels that
# appear in German bank statements but are not transactions.
_NOISE_PATTERNS = [
    r"^seite\s+\d+",
    r"^\d+\s*/\s*\d+$",
    r"^nr\.\s+\d{2}/\d{4}",
    r"^kontoauszug\s+nr",
    r"^buchungstag",
    r"^wertstellungstag",
    r"^betrag\s+(soll|haben)",
    r"^beschreibung$",
    r"^verwendungszweck$",
    r"^glaeubiger.id",
    r"dein alter kontostand",
    r"dein neuer kontostand",
    r"alter kontostand",
    r"neuer kontostand",
    r"anfangssaldo",
    r"endsaldo",
    r"^saldo\b",
    r"^kontostand\b",
    r"^closing balance",
    r"^opening balance",
    r"^iban\b",
    r"^bic\b",
    r"^konto\s+\d",
    r"^blz\b",
    r"^bankleitzahl",
    r"ihre?\s+iban",
    r"^uebertrag\s+(von|auf)\s+seite",
    r"^weiter\s+auf\s+seite",
    r"^fortsetzung",
    r"^summe\s+(ein|aus)",
]
_NOISE_RE = re.compile(
    "|".join(f"({p})" for p in _NOISE_PATTERNS),
    re.IGNORECASE,
)

# ── Amount pattern ─────────────────────────────────────────────────────────
# Matches: 1.234,56  or  1234,56  or  1.234.567,89
# Optionally preceded by - for debits in some formats
_AMOUNT_RE = re.compile(r"[+-]?\d{1,3}(?:\.\d{3})*,\d{2}")

# ── Date pattern ──────────────────────────────────────────────────────────
_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")

# ── Keyword maps for categorisation ───────────────────────────────────────
_CATEGORY_KEYWORDS: list[tuple[TransactionCategory, list[str]]] = [
    (
        TransactionCategory.HOUSING,
        ["miete", "wohnung", "wohngenossenschaft", "hausgeld", "nebenkosten"],
    ),
    (
        TransactionCategory.UTILITIES,
        [
            "stadtwerke",
            "strom",
            "gas",
            "wasser",
            "müll",
            "mobilfunk",
            "internet",
            "telekom",
            "vodafone",
            "o2",
        ],
    ),
    (
        TransactionCategory.GROCERIES,
        [
            "supermarkt",
            "rewe",
            "edeka",
            "aldi",
            "lidl",
            "kaufland",
            "netto",
            "penny",
            "norma",
            "lebensmittel",
        ],
    ),
    (
        TransactionCategory.TRANSPORT,
        [
            "db ",
            "bahn",
            "mvv",
            "hvv",
            "bvg",
            "tankstelle",
            "shell",
            "aral",
            "esso",
            "benzin",
            "parken",
        ],
    ),
    (
        TransactionCategory.HEALTHCARE,
        ["apotheke", "arzt", "krankenhaus", "krankenkasse", "aok", "tk ", "barmer"],
    ),
    (
        TransactionCategory.DINING,
        ["restaurant", "café", "cafe", "bistro", "pizza", "burger", "mcdonald", "subway"],
    ),
    (
        TransactionCategory.ENTERTAINMENT,
        ["netflix", "spotify", "amazon prime", "disney", "kino", "theater"],
    ),
    (
        TransactionCategory.SHOPPING,
        ["amazon", "zalando", "otto", "ebay", "dm ", "rossmann", "müller"],
    ),
    (TransactionCategory.INVESTMENT, ["depot", "wertpapier", "aktien", "fonds", "etf", "sparplan"]),
    (TransactionCategory.SAVINGS, ["sparkonto", "tagesgeld", "festgeld", "sparen"]),
    (TransactionCategory.TRANSFER, ["überweisung", "umbuchung", "dauerauftrag", "sepa"]),
    (
        TransactionCategory.INCOME,
        ["gehalt", "lohn", "rente", "zahlungseingang", "gutschrift", "db systel", "systel"],
    ),
]

# ── Debit / credit keyword detection ──────────────────────────────────────
_DEBIT_KEYWORDS = [
    "lastschrift",
    "kartenzahlung",
    "dauerauftrag",
    "geldautomat",
    "überweisung",
    "sdirekt",
    "auszahlung",
    "entgelt",
]
_CREDIT_KEYWORDS = [
    # payment received / income
    "zahlungseingang",
    "gutschrift",
    "lohn/gehalt",
    "lohn",
    "gehalt",
    "db systel",
    "systel",
    "rente",
    "kindergeld",
    "erstattung",
    "rückerstattung",
    # deposits and transfers in
    "einzahlung",
    "sb-einzahlung",
    "gutbuchung",
    # specific German bank terms for credits
    "kostenfreie buchung",
    "umbuchung haben",
    # salary-adjacent
    "gehalt abrechnung",
    "lohnzahlung",
    "bezüge",
]


class PdfTextParser(ILLMDocumentParser):
    """
    Extracts transactions from bank statement PDFs using PyMuPDF text extraction
    and regex-based parsing. No network calls — runs entirely locally.

    Strategy:
    1. Extract all text from every PDF page via PyMuPDF
    2. Find the transaction table using date patterns as row anchors
    3. Parse amount, description, and debit/credit from each row
    4. Categorise using keyword matching

    Falls back gracefully — returns empty transactions rather than crashing
    if the PDF format is not recognised.
    """

    async def parse(self, file_bytes: bytes, mime_type: str) -> ExtractionResult:
        if mime_type != "application/pdf":
            raise ValueError(
                f"PdfTextParser only handles PDFs, got: {mime_type}. "
                "Use a vision-based parser for image receipts."
            )
        text = self._extract_text(file_bytes)
        return self._parse_text(text)

    async def is_available(self) -> bool:
        try:
            import fitz  # noqa: F401

            return True
        except ImportError:
            return False

    # ── Text extraction ────────────────────────────────────────────────────

    @staticmethod
    def _extract_text(pdf_bytes: bytes) -> str:
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)

    # ── Main parsing ───────────────────────────────────────────────────────

    def _parse_text(self, text: str) -> ExtractionResult:
        lines = [
            ln.strip()
            for ln in text.splitlines()
            if ln.strip() and not _NOISE_RE.search(ln.strip())
        ]

        account_name = self._find_account_name(lines)
        account_institution = self._find_institution(lines)
        period_start, period_end = self._find_period(lines)
        closing_balance = self._find_closing_balance(lines)
        transactions = self._extract_transactions(lines)

        return ExtractionResult(
            transactions=transactions,
            account_name=account_name,
            account_institution=account_institution,
            statement_period_start=period_start,
            statement_period_end=period_end,
            closing_balance=closing_balance,
            raw_llm_response=text[:500],  # first 500 chars as debug reference
        )

    # ── Transaction extraction ─────────────────────────────────────────────

    def _extract_transactions(self, lines: list[str]) -> list[ExtractedTransaction]:
        transactions: list[ExtractedTransaction] = []
        i = 0
        while i < len(lines):
            date = self._parse_date(lines[i])
            if date:
                # Collect description lines until we find an amount
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
                        transactions.append(
                            ExtractedTransaction(
                                date=date,
                                description=description,
                                amount=amount,
                                transaction_type=tx_type or self._infer_type(description),
                                category=self._categorise(description),
                                merchant=self._extract_merchant(description),
                            )
                        )
                    i = j + 1
                    continue
            i += 1
        return transactions

    # ── Amount parsing ─────────────────────────────────────────────────────

    def _parse_amount_and_type(self, line: str) -> tuple[Decimal | None, TransactionType | None]:
        """
        Parse amount and direction from a line.

        Sparkasse PDF layout has two amount columns side by side:
            Betrag Soll EUR    Betrag Haben EUR
            -790,00                                  ← debit
                               1.752,37              ← credit

        When PyMuPDF extracts text, debits appear in the left column
        and credits in the right. We detect this by:
        1. Explicit Soll/Haben keywords on the line
        2. Leading minus sign = debit
        3. Two amounts on one line = left is debit, right is credit
        4. Fall back to None (caller infers from description keywords)
        """
        match = _AMOUNT_RE.search(line)
        if not match:
            return None, None

        raw = match.group()
        is_negative = raw.startswith("-") or line.strip().endswith("-")
        is_positive = raw.startswith("+")  # N26 explicitly marks credits with +
        normalized = raw.lstrip("+-").replace(".", "").replace(",", ".")

        try:
            amount = Decimal(normalized)
        except InvalidOperation:
            return None, None

        line_lower = line.lower()

        # N26 explicit + prefix = credit
        if is_positive:
            return amount, TransactionType.CREDIT

        # Explicit column header keywords
        if "soll" in line_lower or is_negative:
            return amount, TransactionType.DEBIT
        if "haben" in line_lower:
            return amount, TransactionType.CREDIT

        # Two amounts on the same line — left=debit, right=credit
        all_matches = _AMOUNT_RE.findall(line)
        if len(all_matches) == 2:
            # Position of match determines column
            pos = match.start()
            midpoint = len(line) // 2
            tx_type = TransactionType.DEBIT if pos < midpoint else TransactionType.CREDIT
            return amount, tx_type

        return amount, None  # inferred from description by caller

    # ── Date parsing ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_date(line: str) -> Date | None:
        match = _DATE_RE.match(line.strip())
        if not match:
            return None
        try:
            return datetime.strptime(
                f"{match.group(1)}.{match.group(2)}.{match.group(3)}", "%d.%m.%Y"
            ).date()
        except ValueError:
            return None

    # ── Metadata extraction ────────────────────────────────────────────────

    @staticmethod
    def _find_account_name(lines: list[str]) -> str | None:
        for i, line in enumerate(lines):
            if "herrn" in line.lower() or "frau" in line.lower():
                if i + 1 < len(lines):
                    return lines[i + 1]
        return None

    @staticmethod
    def _find_institution(lines: list[str]) -> str | None:
        for line in lines[:20]:
            lower = line.lower()
            for bank in [
                "sparkasse",
                "volksbank",
                "ing",
                "dkb",
                "commerzbank",
                "deutsche bank",
                "postbank",
                "comdirect",
                "n26",
            ]:
                if bank in lower:
                    return line
        return None

    @staticmethod
    def _find_period(lines: list[str]) -> tuple[Date | None, Date | None]:
        start: Date | None = None
        end: Date | None = None
        for line in lines:
            lower = line.lower()
            if "kontostand am" in lower or "auszug" in lower:
                dates = _DATE_RE.findall(line)
                for d, m, y in dates:
                    try:
                        parsed = datetime.strptime(f"{d}.{m}.{y}", "%d.%m.%Y").date()
                        if start is None:
                            start = parsed
                        else:
                            end = parsed
                    except ValueError:
                        pass
        return start, end

    @staticmethod
    def _find_closing_balance(lines: list[str]) -> Decimal | None:
        for line in lines:
            lower = line.lower()
            if "kontostand" in lower or "saldo" in lower:
                match = _AMOUNT_RE.search(line)
                if match:
                    try:
                        return Decimal(match.group().lstrip("-").replace(".", "").replace(",", "."))
                    except InvalidOperation:
                        pass
        return None

    # ── Classification helpers ─────────────────────────────────────────────

    @staticmethod
    def _infer_type(description: str) -> TransactionType:
        """
        Infer transaction direction from description keywords.
        Credit keywords are checked first — false negatives (missed credits)
        are worse than false positives for a finance app.
        """
        lower = description.lower()
        for kw in _CREDIT_KEYWORDS:
            if kw in lower:
                return TransactionType.CREDIT
        for kw in _DEBIT_KEYWORDS:
            if kw in lower:
                return TransactionType.DEBIT
        # If no keyword matches, default to debit — most transactions are expenses
        return TransactionType.DEBIT

    @staticmethod
    def _categorise(description: str) -> TransactionCategory:
        lower = description.lower()
        for category, keywords in _CATEGORY_KEYWORDS:
            if any(kw in lower for kw in keywords):
                return category
        return TransactionCategory.OTHER

    @staticmethod
    def _extract_merchant(description: str) -> str | None:
        """Return first meaningful word/phrase as merchant hint."""
        words = description.split()
        if words:
            return words[0].title()
        return None
