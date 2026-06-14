import pathlib

import pymupdf

from readers.bank_statement_reader import BankStatementReader
from readers.entry_processor.bank_entry_processor import BankEntryProcessor
from readers.entry_processor.n26_entry_processor import N26EntryProcessor
from readers.entry_processor.sparkasse_entry_processor import SparkasseEntryProcessor
from readers.n26_reader import N26Reader
from readers.sparkasse_reader import SparkasseReader


class StatementOrchestrator:
    """Detects bank signatures inside a document and wires the correct components."""

    @staticmethod
    def get_components(file_path: pathlib.Path) -> tuple[BankStatementReader, BankEntryProcessor]:
        # Peek at the first page text to fingerprint the specific bank
        with pymupdf.open(file_path) as doc:
            if not doc:
                raise ValueError("The uploaded PDF is empty or invalid.")
            first_page_text = doc[0].get_text("text")

        # Match signatures dynamically and return initialized component pairs
        if "Sparkasse" in first_page_text:
            return SparkasseReader(file_path), SparkasseEntryProcessor()

        if "N26" in first_page_text or "Dein neuer Kontostand" in first_page_text:
            return N26Reader(file_path), N26EntryProcessor()

        raise ValueError("Unsupported bank statement layout profile.")
