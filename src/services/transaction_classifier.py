import logging
import re
from typing import Optional

from models.bank_statement import BankStatement
from models.bank_transaction import BankTransaction

# 1. Initialize standard logger module configuration context
logger = logging.getLogger("transaction_classifier")
logger.setLevel(logging.INFO)

# Avoid adding duplicate handlers if the classifier class is re-imported
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class TransactionClassifier:
    """Classifies transaction items using regex matching logic architectures."""

    RULES = {
        "FIXED_COSTS": r"Easy Fitness|Fitness Forum|Netflix|BMW Bank|Entgeltabrechnung",
        "BENZIN": r"Tankstelle|Tamoil|HEM|Shell|Aral|TotalEnergies",
        "CHARGING": r"Shell Recharge|IONITY|EnBW mobility|ChargePoint|Charge|E-Mobility",
        "PARKING": r"Parkhaus|APCOA|Q-Park|Park|Parkgarage",
        "GROCERIES": r"Kaufland|SCHECK-IN|REWE|EDEKA|LIDL|ALDI",
        "ONLINE_SHOPPING": r"Amazon",
        "REMITTANCE": r"Wise Europe",
        "SALARY": r"Lohn, Gehalt|DB Systel|Verdienstabrechnung",
        "RETURNS": r"Finanzamt|Erstatt|dividend",
        "TRAVEL": r"Deutsche Bahn|FlixBus|Eurowings|Ryanair|Lufthansa|Booking|Airbnb|Uber|Lyft|Hotel|Reise",
        "BANK_TRANSFER": r"Investment|Fonds|investments|Stocks|Etfs|Srocks",
        "INVESTMENT_ORDER": r"payment hold for buy",
    }

    @classmethod
    def assign_category(cls, description: str, amount: float) -> str:
        # Clean description whitespace lines for compact tracking print statements
        clean_desc = description.replace("\n", " ").strip()

        # 1. Evaluate predefined category regex patterns first
        for category, pattern in cls.RULES.items():
            if re.search(pattern, description, re.IGNORECASE):
                logger.info(f"MATCH FOUND: '{clean_desc[:50]}...' -> {category} (Rule: {pattern})")
                return category

        # 2. Fallback routing categories based on currency flow direction
        fallback = "OTHER_EXPENSE" if amount < 0 else "OTHER_INCOME"
        logger.info(f"FALLBACK APPLIED: '{clean_desc[:50]}...' -> {fallback}")
        return fallback

    @classmethod
    def link_internal_transfers(cls, statements: list[BankStatement]):
        all_txs = []
        for stmt in statements:
            for tx in stmt.transactions:
                tx.category = cls.assign_category(tx.description, tx.amount)
                all_txs.append({"tx": tx, "bank": stmt.bank})

        # Match and link the Sparkasse -> N26 pipeline
        for item_a in all_txs:
            tx_a = item_a["tx"]
            if tx_a.category != "BANK_TRANSFER" or tx_a.amount >= 0:
                continue

            for item_b in all_txs:
                tx_b = item_b["tx"]
                if (
                    tx_b.category == "BANK_TRANSFER"
                    and tx_b.amount == abs(tx_a.amount)
                    and item_a["bank"] != item_b["bank"]
                ):
                    tx_a.category = "INTERNAL_TRANSFER_OUT"
                    tx_b.category = "INTERNAL_TRANSFER_IN"
                    break
