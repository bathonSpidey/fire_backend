import datetime
import pathlib

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database.models import DBBankStatement, DBIngestJob, DBReceipt
from database.session import get_db
from models.statement import Bank
from services import ingest_worker
from services.document_ingest import (
    AUTO,
    KINDS,
    move_back_to_inbox,
    save_group_to_inbox,
    save_to_inbox,
)
from services.receipt_store import confirm_receipt, delete_receipt
from services.statement_store import delete_statement

router = APIRouter(prefix="/documents", tags=["Document Ingestion"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class JobOut(BaseModel):
    id: int
    kind: str
    owner: str
    original_name: str
    status: str
    message: str | None
    receipt_id: int | None  # for statements: the statement id
    cost_usd: float | None
    hint: str | None  # the bank the uploader named
    created_at: str
    finished_at: str | None

    @classmethod
    def from_row(cls, job: DBIngestJob) -> "JobOut":
        return cls(
            id=job.id,
            kind=job.kind,
            owner=job.owner,
            original_name=job.original_name,
            status=job.status,
            message=job.message,
            receipt_id=job.receipt_id,
            cost_usd=job.cost_usd,
            hint=job.hint,
            created_at=job.created_at.isoformat() + "Z",
            finished_at=job.finished_at.isoformat() + "Z" if job.finished_at else None,
        )


def _check_bank(value: str | None) -> str | None:
    """The bank the uploader named (only useful for screenshots without a header)."""
    hint = (value or "").strip() or None
    if hint and hint not in {b.value for b in Bank}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown bank '{hint}'.")
    return hint


@router.get("/owners")
def list_owners() -> list[str]:
    return settings.FIRE_OWNERS


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_documents(
    owner: str = Form(...),
    kind: str = Form(AUTO),
    group: bool = Form(False),
    bank_hint: str = Form(""),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Accept receipts and/or statements and queue them; extraction runs in the background.

    Claude decides per document whether it is a receipt or a statement (kind=auto). With
    group=true all files form ONE document (e.g. screenshots of one statement, in the order
    given). Returns immediately. Poll GET /documents/jobs to follow progress.
    """
    if owner not in settings.FIRE_OWNERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown owner '{owner}'.")
    if kind not in KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown kind '{kind}'.")
    hint = _check_bank(bank_hint)

    uploads: list[tuple[str, bytes]] = []
    rejected: list[dict] = []
    for upload in files:
        data = await upload.read()
        if len(data) > MAX_UPLOAD_BYTES:
            rejected.append({"filename": upload.filename, "reason": "File larger than 20 MB."})
        else:
            uploads.append((upload.filename or "upload", data))

    jobs: list[DBIngestJob] = []
    if group and len(uploads) > 1:
        try:
            folder = save_group_to_inbox(owner, uploads, kind)
        except ValueError as exc:  # one bad file rejects the whole group: it is one document
            rejected.append({"filename": ", ".join(name for name, _ in uploads), "reason": str(exc)})
        else:
            names = ", ".join(name for name, _ in uploads)
            jobs.append(
                DBIngestJob(
                    owner=owner,
                    kind=kind,
                    original_name=f"{len(uploads)} files: {names}"[:200],
                    inbox_path=str(folder),
                    status="queued",
                )
            )
    else:
        for name, data in uploads:
            try:
                inbox_file = save_to_inbox(owner, name, data, kind)
            except ValueError as exc:
                rejected.append({"filename": name, "reason": str(exc)})
                continue
            jobs.append(
                DBIngestJob(
                    owner=owner, kind=kind, original_name=name,
                    inbox_path=str(inbox_file), status="queued",
                )
            )
    for job in jobs:
        job.hint = hint
        db.add(job)
    db.commit()

    for job in jobs:
        ingest_worker.enqueue(job.id)
    return {"jobs": [JobOut.from_row(j) for j in jobs], "rejected": rejected}


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    rows = db.query(DBIngestJob).order_by(DBIngestJob.id.desc()).limit(limit).all()
    return [JobOut.from_row(j) for j in rows]


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_job(job_id: int, db: Session = Depends(get_db)):
    """Queue a failed job again without uploading anything again.

    Documents are read anew with auto-detection (an old failure may have been a wrong guess or a
    system problem). The failed row stays as history and points to the new job.
    """
    job = db.get(DBIngestJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job.")
    if job.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed jobs can be retried.")
    if "Retried as job" in (job.message or ""):
        raise HTTPException(status.HTTP_409_CONFLICT, "This job was already retried.")

    if job.kind == "recategorize":
        new = DBIngestJob(owner=job.owner, kind="recategorize", original_name=job.original_name,
                          inbox_path=job.inbox_path, status="queued")
    else:
        source = next(
            (pathlib.Path(p) for p in (job.filed_path, job.inbox_path) if p and pathlib.Path(p).exists()),
            None,
        )
        if source is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "The uploaded file is no longer available; please upload it again.")
        new = DBIngestJob(owner=job.owner, kind=AUTO, original_name=job.original_name,
                          inbox_path=str(move_back_to_inbox(source, job.owner)), status="queued")
    db.add(new)
    db.flush()
    job.message = f"{job.message or ''} [Retried as job #{new.id}]".strip()
    db.commit()
    ingest_worker.enqueue(new.id)
    return JobOut.from_row(new)


class RereadIn(BaseModel):
    bank_hint: str | None = None


class ConfirmIn(BaseModel):
    purchase_date: datetime.date | None = None  # receipts: correct the date while confirming


def _stored_record(db: Session, job: DBIngestJob):
    """The receipt or statement a finished job produced, or None if it is gone."""
    if job.status not in ("saved", "needs_review") or job.kind not in ("receipt", "statement"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only stored receipts and statements can do that.")
    table = DBReceipt if job.kind == "receipt" else DBBankStatement
    record = db.get(table, job.receipt_id)  # for statements this holds the statement id
    if record is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That record no longer exists.")
    return record


@router.post("/jobs/{job_id}/reread", status_code=status.HTTP_202_ACCEPTED)
def reread_job(job_id: int, body: RereadIn = Body(default_factory=RereadIn), db: Session = Depends(get_db)):
    """Claude got it wrong: remove what was stored and read the same file again.

    The stored record is deleted cleanly (bank links and questions that pointed at it are
    released), the original file goes back to the inbox, and a new job reads it fresh. For a
    statement you can name the bank, which Claude must then use.
    """
    job = db.get(DBIngestJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job.")
    if "Read again as job" in (job.message or ""):
        raise HTTPException(status.HTTP_409_CONFLICT, "This was already read again.")
    if "Merged into" in (job.message or ""):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This upload was merged into the month's PayPal list; reading it again would remove the "
            "whole month. Upload the missing screenshots instead.",
        )
    hint = _check_bank(body.bank_hint)
    record = _stored_record(db, job)
    source = pathlib.Path(record.source_path or job.filed_path or "")
    if not source.exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "The original file is no longer available; please upload it again.")

    inbox_path = move_back_to_inbox(source, job.owner)  # first: a failure here must not lose data
    (delete_receipt if job.kind == "receipt" else delete_statement)(db, record)
    new = DBIngestJob(owner=job.owner, kind=AUTO, original_name=job.original_name,
                      inbox_path=str(inbox_path), status="queued", hint=hint)
    db.add(new)
    db.flush()
    job.message = f"{job.message or ''} [Read again as job #{new.id}]".strip()
    db.commit()
    ingest_worker.enqueue(new.id)
    return JobOut.from_row(new)


@router.post("/jobs/{job_id}/confirm")
def confirm_job(job_id: int, body: ConfirmIn = Body(default_factory=ConfirmIn), db: Session = Depends(get_db)):
    """The household checked a flagged document and it is fine (a receipt's date can be fixed)."""
    job = db.get(DBIngestJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job.")
    record = _stored_record(db, job)
    if job.kind == "receipt":
        confirm_receipt(db, record, body.purchase_date)
    else:
        # The note stays: it also records that this statement had no balances to verify against.
        record.status = "ok"
    job.status = "saved"
    job.message = f"{(job.message or '').split(' Please check:')[0]} [Checked]".strip()
    db.commit()
    return JobOut.from_row(job)
