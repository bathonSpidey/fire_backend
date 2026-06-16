from pydantic import BaseModel


class BankTransaction(BaseModel):
    date: str
    description: str
    amount: float
    category: str | None = None
