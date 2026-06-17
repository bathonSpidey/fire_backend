import pathlib

import pytesseract

from extractor.inventory_extractor import InventoryExtractor

file_path = pathlib.Path(__file__).parent / "data" / "kaufland_small.png"




class TestKauflandReceiptExtractor:
    def test_extract(self):
        extractor = InventoryExtractor()
        receipt = extractor.extract_structured_receipt(file_path)
        assert receipt.store_name == "Kaufland"
        assert receipt.total_amount == 24.45
        assert len(receipt.items) > 0
