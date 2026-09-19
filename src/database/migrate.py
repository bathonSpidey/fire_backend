"""Apply pending Alembic migrations at startup, backing up the SQLite file first.

Lets a plain `uvicorn main:app` start against an older database without a separate manual step.
"""

import logging
import pathlib
import shutil
from datetime import datetime

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from config import ROOT_DIR, settings

logger = logging.getLogger("fire.migrate")


def _alembic_config() -> Config:
    # No ini file on purpose: env.py would otherwise reconfigure logging and silence uvicorn.
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.FIRE_DATABASE_URL)
    return cfg


def upgrade_to_head() -> None:
    cfg = _alembic_config()
    head = ScriptDirectory.from_config(cfg).get_current_head()
    engine = create_engine(settings.FIRE_DATABASE_URL)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
        db_file = engine.url.database
    finally:
        engine.dispose()

    if current == head:
        return

    if current is not None and db_file and pathlib.Path(db_file).exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = pathlib.Path(f"{db_file}.backup-{current}-{stamp}")
        shutil.copy2(db_file, backup)
        logger.warning("Database schema %s -> %s. Backup saved to %s", current, head, backup)

    command.upgrade(cfg, "head")
    logger.warning("Database migrated to %s", head)
