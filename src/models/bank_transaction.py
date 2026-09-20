from pydantic import BaseModel


class BankTransaction(BaseModel):
    date: str
    description: str
    amount: float
    category: str | None = None
    inventory_purchase_id: int | None = None
    # Set for statements read by Claude (see bank_transactions); None for old-parser rows
    counterparty: str | None = None
    kind: str | None = None
    transfer_group: int | None = None
