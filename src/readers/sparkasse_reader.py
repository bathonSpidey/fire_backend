import pathlib
import re

from readers.bank_statement_reader import BankStatementReader


class SparkasseReader(BankStatementReader):
    """Concrete implementation specialized ONLY for Sparkasse layouts."""

    def __init__(self, file_path: str | pathlib.Path):
        super().__init__(file_path)
        self._tx_pattern = r"(.*?)\n\s+(-?\d+(?:\.\d+)*,\d{2})"

    def read(self) -> list[tuple[str, str]]:
        raw_text = self._extract_raw_pdf_text(include_page_breaks=False)
        return re.findall(self._tx_pattern, raw_text, re.DOTALL)
