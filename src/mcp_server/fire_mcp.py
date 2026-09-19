"""MCP server handed to a headless `claude -p` run. Exposes exactly one write tool.

Who the receipt belongs to and which file is being processed are fixed by the launching
process via environment variables, so the model can neither pick an owner nor touch other files.
NOTE: stdio transport -> never print to stdout in this process.
"""

import hashlib
import json
import os
import pathlib

from mcp.server.fastmcp import FastMCP

from database.session import SessionLocal
from models.inventory import ReceiptSubmission
from services.receipt_store import save_receipt as store_receipt

mcp = FastMCP("fire")


def file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@mcp.tool()
def save_receipt(receipt: ReceiptSubmission, review_note: str | None = None) -> str:
    """Store the receipt being processed. Call exactly once per file.

    The code verifies that the items add up to total_amount. If they don't, nothing is saved
    and you get a list of what to fix - correct it and call again.
    Only if you have re-read the receipt and it genuinely cannot be reconciled (illegible,
    cut off, missing lines), pass `review_note` explaining why; it is then saved flagged for
    human review instead of being rejected.
    """
    source = pathlib.Path(os.environ["FIRE_SOURCE_FILE"])
    owner = os.environ["FIRE_OWNER"]
    with SessionLocal() as db:
        outcome = store_receipt(
            db,
            owner=owner,
            source_path=str(source),
            file_hash=file_sha256(source),
            sub=receipt,
            review_note=review_note,
        )
    # Deterministic hand-off to the launching process (last call wins).
    pathlib.Path(os.environ["FIRE_RESULT_FILE"]).write_text(
        json.dumps(
            {
                "ok": outcome.ok,
                "duplicate": outcome.duplicate,
                "receipt_id": outcome.receipt_id,
                "message": outcome.message,
            }
        )
    )
    return outcome.message


if __name__ == "__main__":
    mcp.run(transport="stdio")
