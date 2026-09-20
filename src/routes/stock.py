import datetime
import pathlib
import tempfile

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database.session import get_db
from services import stock
from services.claude_runner import run_claude

router = APIRouter(prefix="/stock", tags=["Stock"])


class UseIn(BaseModel):
    amount: float = 1.0


class DiscardIn(BaseModel):
    reason: str  # expired | spoiled | disliked | too_much | other | gave_away
    amount: float | None = None  # default: everything that is left


class ItemPatch(BaseModel):
    location: str | None = None
    date_expiry: datetime.date | None = None
    rating: int | None = None
    would_rebuy: bool | None = None


def _guard(action):
    try:
        return action()
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except stock.StockError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("")
def list_stock(db: Session = Depends(get_db)) -> dict:
    """Everything that is at home, most urgent first, with a summary."""
    items = stock.stock_items(db)
    return {"items": items, "summary": stock.stock_summary(items)}


@router.post("/clear-stale")
def clear_stale(db: Session = Depends(get_db)) -> dict:
    """Mark everything long past its date as already used up (not as waste)."""
    return stock.clear_stale(db)


@router.get("/insights")
def get_insights(days: int = Query(90, ge=7, le=730), db: Session = Depends(get_db)) -> dict:
    """The zero-waste picture: waste, saved-in-time, repeat offenders, duplicates, favourites."""
    return stock.insights(db, days=days)


@router.post("/items/{item_id}/use")
def use(item_id: int, body: UseIn, db: Session = Depends(get_db)) -> dict:
    return _guard(lambda: stock.use_item(db, item_id, body.amount))


@router.post("/items/{item_id}/finish")
def finish(item_id: int, db: Session = Depends(get_db)) -> dict:
    return _guard(lambda: stock.finish_item(db, item_id))


@router.post("/items/{item_id}/open")
def open_package(item_id: int, db: Session = Depends(get_db)) -> dict:
    return _guard(lambda: stock.open_item(db, item_id))


@router.post("/items/{item_id}/discard")
def discard(item_id: int, body: DiscardIn, db: Session = Depends(get_db)) -> dict:
    return _guard(lambda: stock.discard_item(db, item_id, body.reason, body.amount))


@router.post("/items/{item_id}/freeze")
def freeze(item_id: int, db: Session = Depends(get_db)) -> dict:
    return _guard(lambda: stock.freeze_item(db, item_id))


@router.patch("/items/{item_id}")
def change(item_id: int, body: ItemPatch, db: Session = Depends(get_db)) -> dict:
    """Where it is kept, its best-before date, how it was liked (also for finished items)."""
    return _guard(lambda: stock.update_item(db, item_id, body.model_dump(exclude_unset=True)))


@router.post("/meal-ideas")
def meal_ideas(db: Session = Depends(get_db)) -> dict:
    """Ask Claude what to cook so the things that go off soon get used. Costs a few cents."""
    prompt = stock.meal_ideas_prompt(stock.stock_items(db))
    if prompt is None:
        return {"ideas": None, "message": "Nothing needs using up in the next week."}
    with tempfile.TemporaryDirectory(prefix="fire_meals_") as work:
        run = run_claude(
            system_prompt=stock.MEAL_SYSTEM_PROMPT,
            prompt=prompt,
            tools=[],
            mcp_env={},
            cwd=pathlib.Path(work),
            timeout=settings.CLAUDE_TIMEOUT_SECONDS,
            allow_read=False,
        )
    if not run.text.strip() or run.timed_out:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, run.error_detail or "Claude did not answer.")
    return {"ideas": run.text.strip(), "message": None, "cost_usd": run.cost_usd}
