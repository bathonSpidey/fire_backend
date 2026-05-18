"""
Dependency injection wiring.

The session factory is lazily initialised on first request.
This ensures the /data volume is mounted and directories exist
before SQLAlchemy tries to open the database file.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from fire.application.use_cases.extract_transactions import ExtractTransactions
from fire.application.use_cases.generate_insights import GenerateInsights
from fire.application.use_cases.get_monthly_summary import GetMonthlySummary
from fire.application.use_cases.ingest_document import IngestDocument
from fire.config.settings import Settings
from fire.domain.entities.storage_config import StorageConfig
from fire.infrastructure.db.session import build_session_factory
from fire.infrastructure.file_storage.local_file_storage import LocalFileStorage
from fire.infrastructure.llm.document_parser_factory import DocumentParserFactory
from fire.infrastructure.llm.ollama_insight_generator import OllamaInsightGenerator
from fire.infrastructure.repositories.account_insight_repositories import InsightRepository
from fire.infrastructure.repositories.document_repository import DocumentRepository
from fire.infrastructure.repositories.transaction_repository import TransactionRepository
from fire.infrastructure.repositories.user_repository import UserRepository

# ── Lazy singletons ───────────────────────────────────────────────────────────
# Initialised on first request — not at import time.
# This ensures /data/db exists before SQLAlchemy touches the filesystem.

_settings: Settings | None = None
_storage_config: StorageConfig | None = None
_session_factory: sessionmaker[Session] | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _get_storage_config() -> StorageConfig:
    global _storage_config
    if _storage_config is None:
        config = StorageConfig(root=_get_settings().fire_data_root)
        config.ensure_directories()
        _storage_config = config
    return _storage_config


def _get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = build_session_factory(_get_storage_config())
    return _session_factory


# ── FastAPI dependency functions ──────────────────────────────────────────────


def get_settings() -> Settings:
    return _get_settings()


def get_storage_config() -> StorageConfig:
    return _get_storage_config()


def get_session_factory() -> sessionmaker[Session]:
    return _get_session_factory()


# ── Repositories ──────────────────────────────────────────────────────────────


def get_user_repo(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> UserRepository:
    return UserRepository(factory)


def get_document_repo(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> DocumentRepository:
    return DocumentRepository(factory)


def get_transaction_repo(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> TransactionRepository:
    return TransactionRepository(factory)


def get_insight_repo(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> InsightRepository:
    return InsightRepository(factory)


def get_file_storage(
    config: StorageConfig = Depends(get_storage_config),
) -> LocalFileStorage:
    return LocalFileStorage(files_root=config.files_root)


def get_parser_factory(
    settings: Settings = Depends(get_settings),
) -> DocumentParserFactory:
    return DocumentParserFactory(settings)


def get_insight_generator(
    settings: Settings = Depends(get_settings),
) -> OllamaInsightGenerator:
    return OllamaInsightGenerator(
        base_url=settings.ollama_base_url,
        model=settings.ollama_text_model,
    )


# ── Use cases ─────────────────────────────────────────────────────────────────


def get_ingest_use_case(
    document_repo: DocumentRepository = Depends(get_document_repo),
    file_storage: LocalFileStorage = Depends(get_file_storage),
) -> IngestDocument:
    return IngestDocument(document_repo=document_repo, file_storage=file_storage)


def get_monthly_summary_use_case(
    transaction_repo: TransactionRepository = Depends(get_transaction_repo),
) -> GetMonthlySummary:
    return GetMonthlySummary(transaction_repo=transaction_repo)


def get_generate_insights_use_case(
    insight_repo: InsightRepository = Depends(get_insight_repo),
    insight_generator: OllamaInsightGenerator = Depends(get_insight_generator),
) -> GenerateInsights:
    return GenerateInsights(
        insight_repo=insight_repo,
        llm_generator=insight_generator,
    )
