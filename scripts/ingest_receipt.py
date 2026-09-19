"""Ingest receipt files from the command line.

    uv run python scripts/ingest_receipt.py --owner Abir path/to/receipt.pdf [more files...]

Point it at a scratch DB/workspace first to try it without touching real data:
    FIRE_DATABASE_URL=sqlite:///E:/tmp/scratch.db FIRE_WORKSPACE_ROOT=E:/tmp/ws \
        uv run python scripts/ingest_receipt.py --create-tables --owner Abir file.pdf
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from database.models import Base  # noqa: E402
from database.session import SessionLocal, engine  # noqa: E402
from services.receipt_ingest import ingest_receipt, save_to_inbox  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--create-tables", action="store_true", help="scratch databases only")
    parser.add_argument("files", nargs="+", type=pathlib.Path)
    args = parser.parse_args()

    if args.create_tables:
        Base.metadata.create_all(engine)

    with SessionLocal() as db:
        for path in args.files:
            inbox_file = save_to_inbox(args.owner, path.name, path.read_bytes())
            result = ingest_receipt(args.owner, inbox_file, db)
            cost = f"${result.cost_usd:.3f}" if result.cost_usd is not None else "n/a"
            print(f"[{result.status.upper()}] {path.name}: {result.message}")
            print(f"    -> {result.filed_path}  ({result.seconds:.0f}s, {result.turns} turns, {cost})")


if __name__ == "__main__":
    main()
