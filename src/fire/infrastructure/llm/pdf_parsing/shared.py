"""
Shared regex patterns, constants, and utilities used by all PDF bank parsers.
"""

import re
from datetime import date as Date
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fire.domain.entities.transaction import TransactionCategory, TransactionType
from fire.domain.interfaces.services import ExtractedTransaction

# ── Amount pattern ────────────────────────────────────────────────────────────
# Matches: 1.234,56 or 1234,56 — optionally preceded by +/- for N26
_AMOUNT_RE = re.compile(r"[+-]?\d{1,3}(?:\.\d{3})*,\d{2}")

# ── Date pattern ──────────────────────────────────────────────────────────────
_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")

# ── Shared noise patterns — headers/footers common to all German banks ────────
_SHARED_NOISE = [
    r"^seite\s+\d+",
    r"^\d+\s*/\s*\d+$",
    r"^kontoauszug\s+nr",
    r"^buchungstag",
    r"^wertstellungstag",
    r"^betrag\s+(soll|haben)",
    r"^beschreibung$",
    r"^verwendungszweck$",
    r"anfangssaldo",
    r"endsaldo",
    r"^saldo\b",
    r"^closing\s+balance",
    r"^opening\s+balance",
    r"^iban\b",
    r"^bic\b",
    r"^bankleitzahl",
    r"^summe\s+(ein|aus)",
    r"^fortsetzung",
    r"^weiter\s+auf\s+seite",
]

# ── Category keyword map ──────────────────────────────────────────────────────
CATEGORY_KEYWORDS: list[tuple[TransactionCategory, list[str]]] = [
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
    (
        TransactionCategory.INVESTMENT,
        [
            "depot",
            "wertpapier",
            "aktien",
            "fonds",
            "etf",
            "sparplan",
            "payment hold for buy",
            "belastungen n26",
            "gutschriften n26",
            "cash dividend",
            "tax refund",
            "payment hold",
        ],
    ),
    (TransactionCategory.SAVINGS, ["sparkonto", "tagesgeld", "festgeld", "sparen"]),
    (TransactionCategory.TRANSFER, ["überweisung", "umbuchung", "dauerauftrag", "sepa"]),
    (
        TransactionCategory.INCOME,
        ["gehalt", "lohn", "rente", "zahlungseingang", "gutschrift", "db systel", "systel"],
    ),
]

DEBIT_KEYWORDS = [
    "lastschrift",
    "kartenzahlung",
    "dauerauftrag",
    "geldautomat",
    "überweisung",
    "sdirekt",
    "auszahlung",
    "entgelt",
]

CREDIT_KEYWORDS = [
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
    "einzahlung",
    "sb-einzahlung",
    "gutbuchung",
    "kostenfreie buchung",
    "umbuchung haben",
    "gehalt abrechnung",
    "lohnzahlung",
    "bezüge",
]


# ── Shared helpers ────────────────────────────────────────────────────────────


def parse_date(line: str) -> Date | None:
    match = _DATE_RE.match(line.strip())
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group(1)}.{match.group(2)}.{match.group(3)}", "%d.%m.%Y"
        ).date()
    except ValueError:
        return None


def infer_type(description: str) -> TransactionType:
    lower = description.lower()
    for kw in CREDIT_KEYWORDS:
        if kw in lower:
            return TransactionType.CREDIT
    for kw in DEBIT_KEYWORDS:
        if kw in lower:
            return TransactionType.DEBIT
    return TransactionType.DEBIT


def categorise(description: str) -> TransactionCategory:
    lower = description.lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return category
    return TransactionCategory.OTHER


def build_noise_re(extra_patterns: list[str] | None = None) -> re.Pattern:
    patterns = _SHARED_NOISE + (extra_patterns or [])
    return re.compile("|".join(f"({p})" for p in patterns), re.IGNORECASE)


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(page.get_text() for page in doc)
