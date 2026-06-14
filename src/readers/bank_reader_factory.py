import pymupdf

from readers.n26_reader import N26Reader
from readers.sparkasse_reader import SparkasseReader


class BankReaderFactory:
    @staticmethod
    def get_reader(file_path):
        # Quick peak inside the first page to fingerprint the bank identity
        with pymupdf.open(file_path) as doc:
            first_page_text = doc[0].get_text("text")

        # Route dynamically based on text signatures
        if "Sparkasse" in first_page_text:
            return SparkasseReader(file_path)
        elif "N26" in first_page_text or "Dein neuer Kontostand" in first_page_text:
            return N26Reader(file_path)

        raise ValueError("Unsupported bank statement layout.")
