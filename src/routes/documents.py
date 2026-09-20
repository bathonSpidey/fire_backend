from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database.models import DBIngestJob
from database.session import get_db
from services import ingest_worker
import pathlib

from services.document_ingest import AUTO, KINDS, move_back_to_inbox, save_group_to_inbox, save_to_inbox

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
            created_at=job.created_at.isoformat() + "Z",
            finished_at=job.finished_at.isoformat() + "Z" if job.finished_at else None,
        )


@router.get("/owners")
def list_owners() -> list[str]:
    return settings.FIRE_OWNERS


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_documents(
    owner: str = Form(...),
    kind: str = Form(AUTO),
    group: bool = Form(False),
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
