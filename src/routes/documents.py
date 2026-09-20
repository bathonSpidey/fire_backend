from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database.models import DBIngestJob
from database.session import get_db
from services import ingest_worker
from services.receipt_ingest import save_to_inbox

router = APIRouter(prefix="/receipts", tags=["Receipt Ingestion"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class JobOut(BaseModel):
    id: int
    owner: str
    original_name: str
    status: str
    message: str | None
    receipt_id: int | None
    cost_usd: float | None
    created_at: str
    finished_at: str | None

    @classmethod
    def from_row(cls, job: DBIngestJob) -> "JobOut":
        return cls(
            id=job.id,
            owner=job.owner,
            original_name=job.original_name,
            status=job.status,
            message=job.message,
            receipt_id=job.receipt_id,
            cost_usd=job.cost_usd,
            created_at=job.created_at.isoformat() + "Z",
            finished_at=job.finished_at.isoformat() + "Z" if job.finished_at else None,
        )


@router.get("/owners")
def list_owners() -> list[str]:
    return settings.FIRE_OWNERS


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_receipts(
    owner: str = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Accept receipt files and queue them; extraction runs in the background.

    Returns immediately. Poll GET /receipts/jobs to follow progress.
    """
    if owner not in settings.FIRE_OWNERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown owner '{owner}'.")

    jobs: list[DBIngestJob] = []
    rejected: list[dict] = []
    for upload in files:
        data = await upload.read()
        if len(data) > MAX_UPLOAD_BYTES:
            rejected.append({"filename": upload.filename, "reason": "File larger than 20 MB."})
            continue
        try:
            inbox_file = save_to_inbox(owner, upload.filename or "upload", data)
        except ValueError as exc:
            rejected.append({"filename": upload.filename, "reason": str(exc)})
            continue
        job = DBIngestJob(
            owner=owner,
            original_name=upload.filename or inbox_file.name,
            inbox_path=str(inbox_file),
            status="queued",
        )
        db.add(job)
        jobs.append(job)
    db.commit()

    for job in jobs:
        ingest_worker.enqueue(job.id)
    return {"jobs": [JobOut.from_row(j) for j in jobs], "rejected": rejected}


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    rows = db.query(DBIngestJob).order_by(DBIngestJob.id.desc()).limit(limit).all()
    return [JobOut.from_row(j) for j in rows]
