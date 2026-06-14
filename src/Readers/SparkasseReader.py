import pymupdf


import pathlib
import re


class SparkasseReader:
    def __init__(self, file_path):
        self.file_path = pathlib.Path(file_path)
        self.pattern = r"(.*?)\n\s+(-?\d+(?:\.\d+)*,\d{2})"

    def read(self):
        """Reads the PDF and extracts lines of text from all pages."""
        if not self.file_path.exists():
            raise FileNotFoundError(f"The file {self.file_path} does not exist.")

        extracted_lines = []

        # Open the PDF document
        with pymupdf.open(self.file_path) as doc:
            for page in doc:
                # Extract text as a single string per page
                page_dict = page.get_text("dict")
                page_text = page.get_text("text")

                # Split into lines and clean up empty lines
                entries = re.findall(self.pattern, page_text, re.DOTALL)
                # lines = [
                #     line.strip() for line in page_text.split("\n               ") if line.strip()
                # ]
                extracted_lines.extend(entries)

        return extracted_lines
