import pathlib
import re

import pymupdf


class N26Reader:
    def __init__(self, file_path):
        self.file_path = pathlib.Path(file_path)

    def read(self) -> list[tuple[str, str]]:
        if not self.file_path.exists():
            raise FileNotFoundError(f"The file {self.file_path} does not exist.")

        # Combine all text across pages to ensure seamless regex scanning
        full_text = ""
        with pymupdf.open(self.file_path) as doc:
            for page in doc:
                full_text += page.get_text("text") + "\n---PAGE_BREAK---\n"

        extracted_tuples = []

        # 1. Parse Metadata Boundaries from the Summary section (e.g., Page 5)
        start_bal_match = re.search(
            r"Dein alter Kontostand\n\s*([+-]?\d+(?:\.\d+)*,\d{2})€", full_text
        )
        end_bal_match = re.search(
            r"Dein neuer Kontostand\n\s*([+-]?\d+(?:\.\d+)*,\d{2})€", full_text
        )
        date_range_match = re.search(
            r"(\d{2}\.\d{2}\.\d{4})\s+bis\s+(\d{2}\.\d{2}\.\d{4})", full_text
        )

        if start_bal_match and date_range_match:
            start_date = date_range_match.group(1)
            # Append initial tuple mimicking the Sparkasse format structure
            extracted_tuples.append((f"Kontostand am {start_date}", start_bal_match.group(1)))

        # 2. Parse Mid-Statement Active Transactions
        # Pattern captures descriptions up until: \n[Date]\n[Amount]€
        tx_pattern = r"(.*?)\n(\d{2}\.\d{2}\.\d{4})\n([+-]?\d+(?:\.\d+)*,\d{2})€"

        # We only look at the text blocks preceding the Summary section
        tx_body = full_text.split("Dein alter Kontostand")[0]

        # Find all raw matches
        raw_tx_matches = re.findall(tx_pattern, tx_body, re.DOTALL)

        for raw_desc, date_str, amount_str in raw_tx_matches:
            # Clean up page headers/footers if a transaction crosses a page break boundary
            clean_desc = self._strip_pdf_headers(raw_desc.strip())
            # Format to pair date with description just like your Sparkasse entries expect
            formatted_desc = f"{date_str} {clean_desc}"
            extracted_tuples.append((formatted_desc, amount_str))

        # 3. Append final tuple mimicking closing balance tracking structure
        if end_bal_match and date_range_match:
            end_date = date_range_match.group(2)
            extracted_tuples.append((f"Kontostand am {end_date}", end_bal_match.group(1)))

        return extracted_tuples

    def _strip_pdf_headers(self, text: str) -> str:
        """Removes repeated table headers or page artifacts embedded inside split text, generalized for any user."""
        patterns_to_remove = [
            # 1. Matches any Name, Address, IBAN, BIC, Issue Date, and Page Number (e.g., "1 / 6" or "3 / 6")
            r"[A-Z ]+\n[^.\n]+,\s*\d{5}\s+[^.\n]+\nIBAN:.*?\d\s*/\s*\d",
            # 2. Removes the table column headers
            r"Beschreibung\nVerbuchungsdatum\nBetrag",
            # 3. Removes your internal page break markers
            r"---PAGE_BREAK---",
        ]

        cleaned = text
        for pat in patterns_to_remove:
            cleaned = re.sub(pat, "", cleaned, flags=re.DOTALL)

        # Deduplicate multiple consecutive newlines into a single newline
        return re.sub(r"\n+", "\n", cleaned).strip()
