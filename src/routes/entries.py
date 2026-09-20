from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.session import get_db
from services import categories

router = APIRouter(prefix="/entries", tags=["Entries"])


class CategoryIn(BaseModel):
    category: str


def _guard(action):
    try:
        return action()
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except categories.CategoryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.patch("/transactions/{tx_id}")
def change_transaction_category(tx_id: int, body: CategoryIn, db: Session = Depends(get_db)) -> dict:
    """Change the category of one bank booking (dashboards refresh automatically)."""
    tx = _guard(lambda: categories.set_transaction_category(db, tx_id, body.category))
    return {"id": tx.id, "category": tx.category}


@router.patch("/items/{item_id}")
def change_item_category(item_id: int, body: CategoryIn, db: Session = Depends(get_db)) -> dict:
    """Change the category of one receipt item."""
    item = _guard(lambda: categories.set_item_category(db, item_id, body.category))
    return {"id": item.id, "category": item.spend_category}
