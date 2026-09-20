import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.models import DBIngestJob
from database.session import get_db
from services import categories, ingest_worker, recategorize

router = APIRouter(prefix="/categories", tags=["Categories"])


class CategoryOut(BaseModel):
    key: str
    label: str
    group_name: str
    flow: str
    fixed: bool
    description: str | None
    sort_order: int
    active: bool
    items: int  # receipt items using it
    transactions: int  # bank bookings using it


class CategoryIn(BaseModel):
    label: str
    group_name: str
    flow: str = "expense"
    description: str = ""
    fixed: bool = False


class CategoryPatch(BaseModel):
    label: str | None = None
    group_name: str | None = None
    description: str | None = None
    fixed: bool | None = None
    active: bool | None = None


class MergeIn(BaseModel):
    into: str


class RecheckIn(BaseModel):
    from_categories: list[str] | None = None  # None = every entry
    include_uncategorized: bool = True
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    dry_run: bool = False  # only count the entries; costs nothing


def _out(cat, usage) -> CategoryOut:
    used = usage.get(cat.key)
    return CategoryOut(
        key=cat.key, label=cat.label, group_name=cat.group_name, flow=cat.flow, fixed=bool(cat.fixed),
        description=cat.description, sort_order=cat.sort_order, active=bool(cat.active),
        items=used.items if used else 0, transactions=used.transactions if used else 0,
    )


def _fail(exc: categories.CategoryError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    usage = categories.usage_counts(db)
    return [_out(c, usage) for c in categories.category_map(db, include_inactive=True).values()]


@router.get("/uncategorized")
def uncategorized_usage(db: Session = Depends(get_db)) -> dict:
    used = categories.usage_counts(db).get(None)
    return {"items": used.items if used else 0, "transactions": used.transactions if used else 0}


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryIn, db: Session = Depends(get_db)):
    try:
        cat = categories.create_category(db, **body.model_dump())
    except categories.CategoryError as exc:
        raise _fail(exc)
    return _out(cat, {})


@router.patch("/{key}", response_model=CategoryOut)
def update_category(key: str, body: CategoryPatch, db: Session = Depends(get_db)):
    try:
        cat = categories.update_category(db, key, **body.model_dump(exclude_unset=True))
    except categories.CategoryError as exc:
        raise _fail(exc)
    return _out(cat, categories.usage_counts(db))


@router.post("/{key}/merge")
def merge_category(key: str, body: MergeIn, db: Session = Depends(get_db)) -> dict:
    """Move all entries of `key` into another category and remove `key`."""
    try:
        items, txs = categories.merge_category(db, key, body.into)
    except categories.CategoryError as exc:
        raise _fail(exc)
    return {"moved_items": items, "moved_transactions": txs}


@router.delete("/{key}")
def delete_category(key: str, db: Session = Depends(get_db)) -> dict:
    """Delete a category; entries that used it become uncategorized (re-check them with Claude)."""
    try:
        items, txs = categories.delete_category(db, key)
    except categories.CategoryError as exc:
        raise _fail(exc)
    return {"uncategorized_items": items, "uncategorized_transactions": txs}


@router.post("/recheck")
def recheck_entries(body: RecheckIn, db: Session = Depends(get_db)) -> dict:
    """Ask Claude to re-check existing entries against the current category list (runs in the
    background like an upload). With dry_run it only reports how many entries would be checked."""
    params = {
        "from_categories": body.from_categories,
        "include_uncategorized": body.include_uncategorized,
        "date_from": body.date_from.isoformat() if body.date_from else None,
        "date_to": body.date_to.isoformat() if body.date_to else None,
    }
    entries = len(recategorize.collect_entries(db, params))
    batches = -(-entries // recategorize.BATCH_SIZE)
    if body.dry_run or entries == 0:
        return {"entries": entries, "batches": batches, "job_id": None}
    job = DBIngestJob(
        owner="household", kind="recategorize",
        original_name=f"Re-check categories ({entries} entries)",
        inbox_path=json.dumps(params), status="queued",
    )
    db.add(job)
    db.commit()
    ingest_worker.enqueue(job.id)
    return {"entries": entries, "batches": batches, "job_id": job.id}
