from datetime import date
from pathlib import Path

import pytest
from src.fire.infrastructure.file_storage.local_file_storage import LocalFileStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(files_root=tmp_path / "files")


async def test_save_creates_daily_folder(storage: LocalFileStorage) -> None:
    await storage.save("receipt.pdf", b"content", date(2024, 3, 5))
    assert (storage._files_root / "05-03").exists()


async def test_save_returns_correct_path(storage: LocalFileStorage) -> None:
    path = await storage.save("statement.pdf", b"data", date(2024, 1, 15))
    assert path == storage._files_root / "15-01" / "statement.pdf"


async def test_save_and_read_roundtrip(storage: LocalFileStorage) -> None:
    content = b"%PDF-fake-content-1234"
    path = await storage.save("doc.pdf", content, date(2024, 1, 1))
    result = await storage.read(path)
    assert result == content


async def test_read_raises_for_missing_file(storage: LocalFileStorage) -> None:
    with pytest.raises(FileNotFoundError):
        await storage.read(Path("/nonexistent/file.pdf"))


async def test_delete_removes_file(storage: LocalFileStorage) -> None:
    path = await storage.save("tmp.pdf", b"data", date(2024, 1, 1))
    assert path.exists()
    await storage.delete(path)
    assert not path.exists()


async def test_compute_hash_is_sha256(storage: LocalFileStorage) -> None:
    content = b"hello world"
    hash_val = await storage.compute_hash(content)
    import hashlib

    assert hash_val == hashlib.sha256(content).hexdigest()
    assert len(hash_val) == 64


async def test_daily_folder_format(storage: LocalFileStorage) -> None:
    folder = storage.daily_folder(date(2024, 12, 3))
    assert folder.name == "03-12"


async def test_save_is_idempotent_overwrites_existing(storage: LocalFileStorage) -> None:
    await storage.save("doc.pdf", b"version1", date(2024, 1, 1))
    path = await storage.save("doc.pdf", b"version2", date(2024, 1, 1))
    content = await storage.read(path)
    assert content == b"version2"
