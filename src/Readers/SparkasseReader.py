import pathlib
import re

import pymupdf


class SparkasseReader:
    def __init__(self, file_path):
        self.file_path = pathlib.Path(file_path)
        self.pattern = r"(.*?)\n\s+(-?\d+(?:\.\d+)*,\d{2})"

    def read(self):
        """Reads the PDF and extracts lines of text from all pages."""
        if not self.file_path.exists():
            raise FileNotFoundError(f"The file {self.file_path} does not exist.")
        extracted_lines = []
        with pymupdf.open(self.file_path) as doc:
            for page in doc:
                page_text = page.get_text("text")
                entries = re.findall(self.pattern, page_text, re.DOTALL)
                extracted_lines.extend(entries)

        return extracted_lines
