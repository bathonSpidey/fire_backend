"""
Detects the bank from PDF text and routes to the correct parser.

The account_name hint (e.g. "N26", "Commerzbank") is used as the
primary signal — the user already told us which bank it is.
Content-based detection is the fallback when no hint is given.

Adding a new bank parser:
  1. Create MyBankPdfParser with a detect(text) classmethod
  2. Add its name to _NAME_TO_PARSER below
"""

import logging

from fire.domain.interfaces.services import ExtractionResult
from fire.infrastructure.llm.pdf_parsing.n26_parser import N26PdfParser
from fire.infrastructure.llm.pdf_parsing.shared import extract_text_from_pdf
from fire.infrastructure.llm.pdf_parsing.sparkasse_parser import SparkassePdfParser

logger = logging.getLogger(__name__)

# Maps account_name hints (case-insensitive) to parser class
_NAME_TO_PARSER: dict[str, str] = {
    "n26": "n26",
    "sparkasse": "sparkasse",
    "volksbank": "sparkasse",
    "ing": "sparkasse",
    "dkb": "sparkasse",
    "commerzbank": "sparkasse",
    "deutsche bank": "sparkasse",
    "postbank": "sparkasse",
    "comdirect": "sparkasse",
}


class PdfBankParserFactory:
    """
    Routes to the correct bank PDF parser.

    Priority:
    1. account_name hint from the user  — most reliable
    2. Content-based detection          — fallback (N26 has unique markers)
    3. SparkasseParser                  — generic German bank default
    """

    def __init__(self) -> None:
        self._n26 = N26PdfParser()
        self._sparkasse = SparkassePdfParser()

    def parse(self, pdf_bytes: bytes, account_name: str | None = None) -> ExtractionResult:
        text = extract_text_from_pdf(pdf_bytes)
        parser_key = self._resolve_parser(text, account_name)

        if parser_key == "n26":
            logger.info("PdfBankParserFactory: using N26 parser (hint=%s)", account_name)
            lines = self._n26.filter_lines(text)
            transactions = self._n26.parse_lines(lines)
            institution = account_name or "N26"
        else:
            logger.info(
                "PdfBankParserFactory: using Sparkasse/generic parser (hint=%s)", account_name
            )
            lines = self._sparkasse.filter_lines(text)
            transactions = self._sparkasse.parse_lines(lines)
            institution = account_name or self._detect_institution(text)

        logger.info("PdfBankParserFactory: extracted %d transactions", len(transactions))

        return ExtractionResult(
            transactions=transactions,
            account_name=None,
            account_institution=institution,
            statement_period_start=None,
            statement_period_end=None,
            closing_balance=None,
            raw_llm_response=text[:500],
        )

    def _resolve_parser(self, text: str, account_name: str | None) -> str:
        # 1. User-supplied name takes priority
        if account_name:
            key = _NAME_TO_PARSER.get(account_name.lower().strip())
            if key:
                return key

        # 2. Content-based detection
        if N26PdfParser.detect(text):
            return "n26"

        return "sparkasse"

    @staticmethod
    def _detect_institution(text: str) -> str | None:
        lower = text[:2000].lower()
        for bank in [
            "sparkasse",
            "volksbank",
            "ing",
            "dkb",
            "commerzbank",
            "deutsche bank",
            "postbank",
            "comdirect",
        ]:
            if bank in lower:
                return bank.title()
        return None
