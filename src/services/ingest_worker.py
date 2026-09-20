"""Background worker: processes queued uploads one at a time.

One at a time on purpose: it keeps subscription usage predictable and avoids parallel
`claude` processes fighting over the same SQLite file. Jobs live in the DB, so anything still
queued when the laptop was switched off is picked up again on the next start.
"""

import datetime
import json
import logging
import pathlib
import queue
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from database.models import DBIngestJob
from database.session import SessionLocal
from services import recategorize
from services.document_ingest import IngestResult, ingest_document

logger = logging.getLogger("fire.ingest_worker")

_queue: "queue.Queue[int | None]" = queue.Queue()
_thread: threading.Thread | None = None


def enqueue(job_id: int) -> None:
    _queue.put(job_id)


def process_job(
    job_id: int,
    session_factory: sessionmaker[Session] = SessionLocal,
    ingest_fn: Callable[[str, str, pathlib.Path, Session], IngestResult] = ingest_document,
    recheck_fn: Callable[[dict, Session], IngestResult] = recategorize.run,
) -> None:
    """Run one job to completion and record the outcome on its row. Never raises."""
    with session_factory() as db:
        job = db.get(DBIngestJob, job_id)
        if job is None or job.status not in ("queued", "processing"):
            return
        job.status = "processing"
        db.commit()  # release SQLite's write lock before the slow Claude call

        try:
            if job.kind == "recategorize":  # not a file: inbox_path holds the job's parameters
                result = recheck_fn(json.loads(job.inbox_path), db)
            else:
                file = pathlib.Path(job.inbox_path)
                if not file.exists():
                    raise FileNotFoundError(f"Uploaded file is gone: {file}")
                result = ingest_fn(job.kind, job.owner, file, db)
            job.status = result.status
            if result.kind:  # auto -> what Claude decided the document is
                job.kind = result.kind
            job.message = result.message
            job.receipt_id = result.receipt_id
            job.filed_path = str(result.filed_path) if result.filed_path else None
            job.cost_usd = result.cost_usd
        except Exception as exc:  # noqa: BLE001 - a bad file must not kill the worker
            logger.exception("Ingest job %s crashed", job_id)
            db.rollback()
            job = db.get(DBIngestJob, job_id)
            job.status = "failed"
            job.message = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.datetime.utcnow()
        db.commit()


def _loop() -> None:
    while True:
        job_id = _queue.get()
        if job_id is None:
            return
        process_job(job_id)


def start() -> None:
    """Start the worker thread and re-queue work left over from a previous run."""
    global _thread
    if _thread and _thread.is_alive():
        return
    with SessionLocal() as db:
        leftovers = (
            db.query(DBIngestJob)
            .filter(DBIngestJob.status.in_(["queued", "processing"]))
            .order_by(DBIngestJob.id)
            .all()
        )
        for job in leftovers:
            job.status = "queued"
            _queue.put(job.id)
        db.commit()
    if leftovers:
        logger.info("Re-queued %d unfinished ingest job(s)", len(leftovers))
    _thread = threading.Thread(target=_loop, name="ingest-worker", daemon=True)
    _thread.start()


def stop() -> None:
    _queue.put(None)
