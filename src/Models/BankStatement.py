from Models.BankTransaction import BankTransaction
from pydantic import BaseModel


class BankStatement(BaseModel):
    month: str
    year: int
    bank: str
    starting_balance: float
    closing_balance: float
    transactions: list[BankTransaction]
