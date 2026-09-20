"""ingest jobs remember which bank the uploader said a statement is from

Revision ID: d8e3f1a7c290
Revises: c4a9d6e2b5f1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8e3f1a7c290"
down_revision: Union[str, Sequence[str], None] = "c4a9d6e2b5f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ingest_jobs", sa.Column("hint", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("ingest_jobs", "hint")
