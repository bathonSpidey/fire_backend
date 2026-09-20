"""Ingest receipts or statements from the command line (same pipeline as the web upload).

    uv run python scripts/ingest_document.py --kind receipt   --owner Abir bon1.pdf bon2.pdf
    uv run python scripts/ingest_document.py --kind statement --owner Abir statement.pdf

Try it on scratch data first (the server applies migrations itself; here use --migrate):
    FIRE_DATABASE_URL=sqlite:///E:/tmp/scratch.db FIRE_WORKSPACE_ROOT=E:/tmp/ws \
        uv run python scripts/ingest_document.py --migrate --owner Abir --kind receipt bon.pdf
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from database.migrate import upgrade_to_head  # noqa: E402
from database.session import SessionLocal  # noqa: E402
from services.document_ingest import KINDS, ingest_document, save_to_inbox  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--kind", choices=sorted(KINDS), default="receipt")
    parser.add_argument("--migrate", action="store_true", help="create/upgrade the database first")
    parser.add_argument("files", nargs="+", type=pathlib.Path)
    args = parser.parse_args()

    if args.migrate:
        upgrade_to_head()

    with SessionLocal() as db:
        for path in args.files:
            inbox_file = save_to_inbox(args.owner, path.name, path.read_bytes(), args.kind)
            result = ingest_document(args.kind, args.owner, inbox_file, db)
            cost = f"${result.cost_usd:.3f}" if result.cost_usd is not None else "n/a"
            print(f"[{result.status.upper()}] {path.name}: {result.message}")
            print(f"    -> {result.filed_path}  ({result.seconds:.0f}s, {result.turns} turns, {cost})")


if __name__ == "__main__":
    main()
