import pathlib

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the root directory path dynamically
ROOT_DIR = pathlib.Path(__file__).parent.parent


class AppSettings(BaseSettings):
    """
    Centralized configuration engine for Smartory.
    Environment variables are automatically mapped, typed, and validated.
    """

    # 1. Core Application Variables (with safe defaults)
    APP_NAME: str = "Smartory API Backend"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # 2. Database Connection Parameters
    # Absolute so subprocesses (the Claude MCP server) resolve the same file
    # regardless of their working directory.
    FIRE_DATABASE_URL: str = f"sqlite:///{(ROOT_DIR / 'bank_statements.db').as_posix()}"

    # 3. Household workspace: uploaded files are filed as
    #    <root>/<Owner>/<Month_Year>/<file>, after extraction reveals the month.
    FIRE_WORKSPACE_ROOT: pathlib.Path = ROOT_DIR / "workspace"
    FIRE_OWNERS: list[str] = ["Abir", "Lena"]

    # 4. Claude Code (headless) used for receipt extraction, logged-in subscription
    CLAUDE_MODEL: str = "claude-sonnet-5"
    CLAUDE_EFFORT: str = "medium"
    CLAUDE_TIMEOUT_SECONDS: int = 240

    # 5. Third-Party Sensitive API Keys (legacy Gemini path, optional now)
    # Using SecretStr prevents the key from leaking into raw print logs or error traces
    GEMINI_API_KEY: SecretStr = SecretStr("")

    # 6. Bind Pydantic directly to your physical .env file configuration
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Skips extra variables in your .env that aren't defined here
    )


# Instantiate a global singleton to import across your service boundaries
settings = AppSettings()
