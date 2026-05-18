"""
Dependency injection wiring.

FastAPI routes declare what they need via Depends().
This module provides the factory functions that build those dependencies.

Dependency tree:
    Settings
        └── StorageConfig
        └── SessionFactory
                └── UserRepository
                └── DocumentRepository
                └── TransactionRepository
                └── AccountRepository
                └── InsightRepository
        └── DocumentParserFactory
                └── PdfTextParser  (local)
                └── GeminiDocumentParser / ClaudeDocumentParser (from settings)
        └── LocalFileStorage
        └── OllamaInsightGenerator

Use cases receive repositories and services via constructor injection.
"""

from functools import lru_cache
from pathlib import Path

from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from src.fire.application.use_cases.extract_transactions import ExtractTransactions
from src.fire.application.use_cases.generate_insights import GenerateInsights
from src.fire.application.use_cases.get_monthly_summary import GetMonthlySummary
from src.fire.application.use_cases.ingest_document import IngestDocument
from src.fire.config.settings import Settings
from src.fire.domain.entities.storage_config import StorageConfig
from src.fire.infrastructure.db.session import build_session_factory
from src.fire.infrastructure.file_storage.local_file_storage import LocalFileStorage
from src.fire.infrastructure.llm.document_parser_factory import DocumentParserFactory
from src.fire.infrastructure.llm.ollama_insight_generator import OllamaInsightGenerator
from src.fire.infrastructure.repositories.account_insight_repositories import InsightRepository
from src.fire.infrastructure.repositories.document_repository import DocumentRepository
from src.fire.infrastructure.repositories.transaction_repository import TransactionRepository
from src.fire.infrastructure.repositories.user_repository import UserRepository

# ── Singletons (built once per process) ──────────────────────────────────────


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_storage_config(settings: Settings = Depends(get_settings)) -> StorageConfig:
    config = StorageConfig(root=settings.fire_data_root)
    config.ensure_directories()
    return config


def get_session_factory(
    config: StorageConfig = Depends(get_storage_config),
) -> sessionmaker[Session]:
    return build_session_factory(config)


# ── Per-request dependencies ──────────────────────────────────────────────────


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


# ── Use case dependencies ─────────────────────────────────────────────────────


def get_ingest_use_case(
    document_repo: DocumentRepository = Depends(get_document_repo),
    file_storage: LocalFileStorage = Depends(get_file_storage),
) -> IngestDocument:
    return IngestDocument(document_repo=document_repo, file_storage=file_storage)


def get_extract_use_case(
    document_repo: DocumentRepository = Depends(get_document_repo),
    transaction_repo: TransactionRepository = Depends(get_transaction_repo),
    file_storage: LocalFileStorage = Depends(get_file_storage),
    parser_factory: DocumentParserFactory = Depends(get_parser_factory),
) -> ExtractTransactions:
    # The parser is chosen based on mime type at call time via the factory
    # We pass the pdf parser as default; routes override per upload
    return ExtractTransactions(
        document_repo=document_repo,
        transaction_repo=transaction_repo,
        llm_parser=parser_factory.get_pdf_parser(),  # overridden per request
        file_storage=file_storage,
    )


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
