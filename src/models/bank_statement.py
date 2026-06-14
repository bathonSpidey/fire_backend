from pydantic import BaseModel

from models.bank_transaction import BankTransaction


class BankStatement(BaseModel):
    month: str
    year: int
    bank: str
    starting_balance: float
    closing_balance: float
    transactions: list[BankTransaction]
