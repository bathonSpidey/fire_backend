"""Print how many uploads are waiting or being read by Claude right now.

Used by restart_fire.ps1: restarting the server in the middle of a document would cut the reading
off, so it waits until this prints 0.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from database.models import DBIngestJob  # noqa: E402
from database.session import SessionLocal  # noqa: E402


def main() -> None:
    with SessionLocal() as db:
        print(db.query(DBIngestJob).filter(DBIngestJob.status.in_(["queued", "processing"])).count())


if __name__ == "__main__":
    main()
