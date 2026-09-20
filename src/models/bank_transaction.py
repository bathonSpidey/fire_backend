from pydantic import BaseModel


class BankTransaction(BaseModel):
    id: int | None = None  # bank_transactions id; lets the UI change one booking's category
    date: str
    description: str
    amount: float
    category: str | None = None
    inventory_purchase_id: int | None = None
    # Set for statements read by Claude (see bank_transactions); None for old-parser rows
    counterparty: str | None = None
    kind: str | None = None
    transfer_group: int | None = None
    mirror_of: int | None = None
