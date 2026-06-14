import pathlib  # noqa: N999
import re

from readers.bank_statement_reader import BankStatementReader


class N26Reader(BankStatementReader):
    """Concrete implementation specialized ONLY for N26 layouts."""

    def __init__(self, file_path: str | pathlib.Path):
        super().__init__(file_path)
        self._tx_pattern = r"(.*?)\n(\d{2}\.\d{2}\.\d{4})\n([+-]?\d+(?:\.\d+)*,\d{2})€"

    def read(self) -> list[tuple[str, str]]:
        full_text = self._extract_raw_pdf_text(include_page_breaks=True)
        return self._parse_layout(full_text)

    def _parse_layout(self, text: str) -> list[tuple[str, str]]:
        extracted_tuples = []

        # Parse boundaries
        start_bal = re.search(r"Dein alter Kontostand\n\s*([+-]?\d+(?:\.\d+)*,\d{2})€", text)
        end_bal = re.search(r"Dein neuer Kontostand\n\s*([+-]?\d+(?:\.\d+)*,\d{2})€", text)
        date_range = re.search(r"(\d{2}\.\d{2}\.\d{4})\s+bis\s+(\d{2}\.\d{2}\.\d{4})", text)

        if start_bal and date_range:
            extracted_tuples.append((f"Kontostand am {date_range.group(1)}", start_bal.group(1)))

        # Parse intermediate transactions
        tx_body = text.split("Dein alter Kontostand")[0]
        raw_tx_matches = re.findall(self._tx_pattern, tx_body, re.DOTALL)

        for raw_desc, date_str, amount_str in raw_tx_matches:
            clean_desc = self._strip_pdf_headers(raw_desc.strip())
            extracted_tuples.append((f"{date_str} {clean_desc}", amount_str))

        if end_bal and date_range:
            extracted_tuples.append((f"Kontostand am {date_range.group(2)}", end_bal.group(1)))

        return extracted_tuples

    def _strip_pdf_headers(self, text: str) -> str:
        patterns_to_remove = [
            r"[A-Z ]+\n[^.\n]+,\s*\d{5}\s+[^.\n]+\nIBAN:.*?\d\s*/\s*\d",
            r"Beschreibung\nVerbuchungsdatum\nBetrag",
            r"---PAGE_BREAK---",
        ]
        cleaned = text
        for pat in patterns_to_remove:
            cleaned = re.sub(pat, "", cleaned, flags=re.DOTALL)
        return re.sub(r"\n+", "\n", cleaned).strip()
