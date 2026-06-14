import re
from abc import ABC, abstractmethod
from datetime import datetime

from models.bank_statement import BankStatement
from models.bank_transaction import BankTransaction


class BankEntryProcessor(ABC):
    """Abstract Base Class implementing the Template Method pattern for processors."""

    def __init__(self, bank_name: str):
        self.bank_name = bank_name

    @abstractmethod
    def _parse_amount(self, amt_str: str) -> float:
        """Handled by concrete class because currency symbols/signs format vary."""
        pass

    @abstractmethod
    def _clean_description(self, desc: str) -> str:
        """Handled by concrete class due to bank-specific layout configurations."""
        pass

    def _determine_statement_date(self, start_desc: str) -> tuple[str, int]:
        """Extracts the short month name and target calendar statement year."""
        day, month, year = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", start_desc).groups()
        
        # Hooks or adjustments like Sparkasse's month shift are handles smoothly
        target_month = int(month) + 1 if day == "31" else int(month)
        month_name = datetime(int(year), target_month, 1).strftime("%b")
        return month_name, int(year)

    def process(self, transactions: list[tuple[str, str]]) -> BankStatement:
        """The Template Method: Defines the rigid workflow step-by-step."""
        if not transactions:
            raise ValueError("Transaction list cannot be empty.")

        start_desc, start_amt = transactions[0]
        _, end_amt = transactions[-1]

        month_name, statement_year = self._determine_statement_date(start_desc)
        tx_list = []

        for desc, amt in transactions[1:-1]:
            date_match = re.search(r"\d{2}\.\d{2}\.\d{4}", desc)
            
            tx_date = date_match.group(0) if date_match else ""
            raw_body = desc[date_match.end():].strip() if date_match else desc.strip()
            
            # Polymorphic execution steps
            clean_body = self._clean_description(raw_body)
            parsed_amount = self._parse_amount(amt)

            tx_list.append(
                BankTransaction(
                    date=tx_date, 
                    description=clean_body, 
                    amount=parsed_amount
                )
            )

        return BankStatement(
            month=month_name,
            year=statement_year,
            bank=self.bank_name,
            starting_balance=self._parse_amount(start_amt),
            closing_balance=self._parse_amount(end_amt),
            transactions=tx_list,
        )