import re

from entry_processor.bank_entry_processor import BankEntryProcessor


class N26EntryProcessor(BankEntryProcessor):
    """Concrete implementation specialized ONLY for N26 transaction parsing."""

    def __init__(self):
        super().__init__(bank_name="N26")

    def _parse_amount(self, amt_str: str) -> float:
        return float(amt_str.replace("+", "").replace(".", "").replace(",", "."))

    def _clean_description(self, desc: str) -> str:
        # Drops any leftover structural fragments at page cut lines
        clean_desc = re.sub(r"^\d{3}\s*\n\s*\d\s*/\s*\d\s*\n", "", desc).strip()

        match = re.search(
            r"N26\s+(.*?)(?:\s*-\s*transaction ID|,\s*paymentId:)", clean_desc, re.IGNORECASE
        )
        if match:
            return match.group(1).strip()
        return clean_desc.split("\n")[-2].strip() if "\n" in clean_desc else clean_desc.strip()
