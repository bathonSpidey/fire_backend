from enum import StrEnum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReceiptProvider(StrEnum):
    GEMINI = "gemini"
    CLAUDE = "claude"
    OLLAMA = "ollama"


class Settings(BaseSettings):
    """
    All configuration for FIRE.
    Read from environment variables or a .env file in the project root.
    Environment variables take precedence over .env values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Storage ───────────────────────────────────────────────────────────────
    fire_data_root: Path = Field(
        default=Path("./data"),
        description="Root directory — files/ and db/ are created here.",
    )

    # ── Receipt provider ──────────────────────────────────────────────────────
    fire_receipt_provider: ReceiptProvider = Field(
        default=ReceiptProvider.GEMINI,
        description="Provider for image receipts. PDFs always use local parser.",
    )

    # ── Gemini ────────────────────────────────────────────────────────────────
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.5-flash")

    # ── Claude ────────────────────────────────────────────────────────────────
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-opus-4-5")

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_vision_model: str = Field(default="gemma4:e2b")
    ollama_text_model: str = Field(default="qwen3:14b-q4_K_M")


def get_settings() -> Settings:
    return Settings()
