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
    DATABASE_URL: str = "sqlite:///./smartory.db"

    # 3. Third-Party Sensitive API Keys
    # Using SecretStr prevents the key from leaking into raw print logs or error traces
    GEMINI_API_KEY: SecretStr

    # 4. Bind Pydantic directly to your physical .env file configuration
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Skips extra variables in your .env that aren't defined here
    )


# Instantiate a global singleton to import across your service boundaries
settings = AppSettings()
