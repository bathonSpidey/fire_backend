"""
Shared fixtures for live integration tests.
These tests require:
  1. Ollama running on localhost:11434
  2. Real fixture files in tests/integration/data/
     - kaufland_small.png
     - kaufland_long.png
     - bank_statement.pdf   (or whatever you named your PDF)

Run them explicitly with:
    uv run pytest -m live
"""

from pathlib import Path

import httpx
import pytest

DATA_DIR = Path(__file__).parent / "data"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live: requires Ollama running locally and real fixture files",
    )


async def _ollama_is_running() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get("http://localhost:11434/api/tags")
            return response.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


@pytest.fixture(scope="session")
def data_dir() -> Path:
    if not DATA_DIR.exists():
        pytest.skip(f"Data directory not found: {DATA_DIR}")
    return DATA_DIR


@pytest.fixture
async def require_ollama() -> None:
    """Fixture that skips the test if Ollama is not reachable."""
    if not await _ollama_is_running():
        pytest.skip("Ollama is not running on localhost:11434 — skipping live test")


@pytest.fixture
def kaufland_small(data_dir: Path) -> bytes:
    candidates = list(data_dir.glob("kaufland*small*")) + list(data_dir.glob("*small*kaufland*"))
    if not candidates:
        pytest.skip("No kaufland small screenshot found in tests/integration/data/")
    return candidates[0].read_bytes()


@pytest.fixture
def kaufland_long(data_dir: Path) -> bytes:
    candidates = list(data_dir.glob("kaufland*long*")) + list(data_dir.glob("*long*kaufland*"))
    if not candidates:
        pytest.skip("No kaufland long screenshot found in tests/integration/data/")
    return candidates[0].read_bytes()


@pytest.fixture
def bank_statement_pdf(data_dir: Path) -> bytes:
    candidates = list(data_dir.glob("*.pdf"))
    if not candidates:
        pytest.skip("No PDF found in tests/integration/data/")
    return candidates[0].read_bytes()
