from dataclasses import dataclass
from datetime import date as Date  # noqa: N812
from pathlib import Path


@dataclass(frozen=True)
class StorageConfig:
    """
    Value object that owns the two root paths for FIRE storage.

    Layout:
        root/
          files/
            DD-MM/          ← one folder per upload day
              <filename>
          db/
            fire.db
    """

    root: Path

    @property
    def files_root(self) -> Path:
        return self.root / "files"

    @property
    def db_root(self) -> Path:
        return self.root / "db"

    @property
    def db_path(self) -> Path:
        return self.db_root / "fire.db"

    def daily_folder(self, upload_date: Date) -> Path:
        """Returns  root/files/DD-MM  — does not create the directory."""
        folder_name = upload_date.strftime("%d-%m")
        return self.files_root / folder_name

    def ensure_directories(self) -> None:
        """Creates root/files/ and root/db/ if they do not exist."""
        self.files_root.mkdir(parents=True, exist_ok=True)
        self.db_root.mkdir(parents=True, exist_ok=True)
