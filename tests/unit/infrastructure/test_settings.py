from pathlib import Path
from unittest.mock import patch

from src.fire.config.settings import ReceiptProvider, Settings


def test_default_receipt_provider_is_gemini() -> None:
    s = Settings()
    assert s.fire_receipt_provider == ReceiptProvider.GEMINI


def test_default_gemini_model() -> None:
    s = Settings()
    assert s.gemini_model == "gemini-2.5-flash"


def test_reads_receipt_provider_from_env() -> None:
    with patch.dict("os.environ", {"FIRE_RECEIPT_PROVIDER": "ollama"}):
        s = Settings()
        assert s.fire_receipt_provider == ReceiptProvider.OLLAMA


def test_reads_gemini_api_key_from_env() -> None:
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key-123"}):
        s = Settings()
        assert s.gemini_api_key == "test-key-123"


def test_data_root_is_path_type() -> None:
    with patch.dict("os.environ", {"FIRE_DATA_ROOT": "/tmp/fire"}):
        s = Settings()
        assert isinstance(s.fire_data_root, Path)
        assert s.fire_data_root == Path("/tmp/fire")


def test_all_providers_are_valid_enum_values() -> None:
    assert ReceiptProvider.GEMINI == "gemini"
    assert ReceiptProvider.CLAUDE == "claude"
    assert ReceiptProvider.OLLAMA == "ollama"
