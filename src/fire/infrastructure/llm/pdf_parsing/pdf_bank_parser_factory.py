"""
Detects the bank from PDF text and routes to the correct parser.

Adding a new bank parser:
  1. Create MyBankPdfParser in its own file with a detect(text) classmethod
  2. Import and add to PARSERS list — most specific first
"""

from fire.domain.interfaces.services import ExtractionResult
from fire.infrastructure.llm.pdf_parsing.n26_parser import N26PdfParser
from fire.infrastructure.llm.pdf_parsing.shared import (
    build_noise_re,
    categorise,
    extract_text_from_pdf,
    infer_type,
    parse_date,
)
from fire.infrastructure.llm.pdf_parsing.sparkasse_parser import SparkassePdfParser


class PdfBankParserFactory:
    """
    Detects the bank from the first 2000 characters of PDF text
    and delegates to the correct parser implementation.
    """

    def __init__(self) -> None:
        self._n26 = N26PdfParser()
        self._sparkasse = SparkassePdfParser()

    def parse(self, pdf_bytes: bytes) -> ExtractionResult:
        from decimal import Decimal

        text = extract_text_from_pdf(pdf_bytes)

        if N26PdfParser.detect(text):
            lines = self._n26.filter_lines(text)
            transactions = self._n26.parse_lines(lines)
            institution = "N26"
        else:
            lines = self._sparkasse.filter_lines(text)
            transactions = self._sparkasse.parse_lines(lines)
            institution = self._detect_institution(text)

        return ExtractionResult(
            transactions=transactions,
            account_name=None,
            account_institution=institution,
            statement_period_start=None,
            statement_period_end=None,
            closing_balance=None,
            raw_llm_response=text[:500],
        )

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
