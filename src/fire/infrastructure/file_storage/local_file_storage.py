import hashlib
from datetime import date as Date
from pathlib import Path

import aiofiles
import aiofiles.os

from src.fire.domain.interfaces.services import IFileStorage


class LocalFileStorage(IFileStorage):
    """
    Stores uploaded files on the local filesystem.

    Layout:
        <root>/files/
            DD-MM/
                <filename>

    Uses async file I/O so it never blocks the FastAPI event loop.
    """

    def __init__(self, files_root: Path) -> None:
        self._files_root = files_root

    async def save(self, filename: str, content: bytes, upload_date: Date) -> Path:
        folder = self.daily_folder(upload_date)
        await aiofiles.os.makedirs(folder, exist_ok=True)
        file_path = folder / filename
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(content)
        return file_path

    async def read(self, file_path: Path) -> bytes:
        async with aiofiles.open(file_path, "rb") as f:
            return await f.read()

    async def delete(self, file_path: Path) -> None:
        await aiofiles.os.remove(file_path)

    async def compute_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def daily_folder(self, upload_date: Date) -> Path:
        return self._files_root / upload_date.strftime("%d-%m")
