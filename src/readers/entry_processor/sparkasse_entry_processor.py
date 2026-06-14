from readers.entry_processor.bank_entry_processor import BankEntryProcessor


class SparkasseEntryProcessor(BankEntryProcessor):
    """Concrete implementation specialized ONLY for Sparkasse transaction parsing."""

    def __init__(self):
        super().__init__(bank_name="Sparkasse")

    def _parse_amount(self, amt_str: str) -> float:
        return float(amt_str.replace(".", "").replace(",", "."))

    def _clean_description(self, desc: str) -> str:
        # Sparkasse doesn't embed long transaction metadata IDs, return description directly
        return desc.strip()
