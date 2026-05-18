"""
API integration tests.
Uses FastAPI TestClient with dependency overrides — real use cases,
real in-memory SQLite, fake file storage and LLM parser.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from src.fire.api.dependencies import (
    get_document_repo,
    get_file_storage,
    get_insight_repo,
    get_parser_factory,
    get_session_factory,
    get_settings,
    get_storage_config,
    get_transaction_repo,
    get_user_repo,
)
from src.fire.config.settings import Settings
from src.fire.domain.entities.transaction import TransactionCategory, TransactionType
from src.fire.domain.interfaces.services import ExtractedTransaction, ExtractionResult
from src.fire.infrastructure.db.models import Base
from src.fire.infrastructure.db.session import build_test_session_factory
from src.fire.infrastructure.llm.document_parser_factory import DocumentParserFactory
from src.fire.infrastructure.repositories.account_insight_repositories import InsightRepository
from src.fire.infrastructure.repositories.document_repository import DocumentRepository
from src.fire.infrastructure.repositories.transaction_repository import TransactionRepository
from src.fire.infrastructure.repositories.user_repository import UserRepository
from src.fire.main import app

from tests.fakes import FakeFileStorage, FakeLLMDocumentParser

# ── Test fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def session_factory():

    # Use a named in-memory DB so all connections share the same data
    engine = create_engine(
        "sqlite:///file::memory:?cache=shared&uri=true",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    # Drop all tables after test to ensure isolation
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def fake_file_storage():
    return FakeFileStorage()


@pytest.fixture
def fake_extraction_result():
    return ExtractionResult(
        transactions=[
            ExtractedTransaction(
                date=date(2024, 1, 15),
                description="Lidl Supermarket",
                amount=Decimal("42.50"),
                transaction_type=TransactionType.DEBIT,
                category=TransactionCategory.GROCERIES,
                merchant="Lidl",
            )
        ],
        account_name="Test Account",
        account_institution="Test Bank",
        statement_period_start=date(2024, 1, 1),
        statement_period_end=date(2024, 1, 31),
        closing_balance=Decimal("1500.00"),
        raw_llm_response="{}",
    )


@pytest.fixture
def client(session_factory, fake_file_storage, fake_extraction_result):

    fake_parser = FakeLLMDocumentParser(result=fake_extraction_result)

    class FakeParserFactory:
        def get_parser_for_mime(self, mime_type: str):
            return fake_parser

        def get_pdf_parser(self):
            return fake_parser

        def get_image_parser(self):
            return fake_parser

    # Override at the repository level — bypass session factory chain entirely
    user_repo = UserRepository(session_factory)
    doc_repo = DocumentRepository(session_factory)
    tx_repo = TransactionRepository(session_factory)
    insight_repo_inst = InsightRepository(session_factory)

    def _user_repo():
        return user_repo

    def _doc_repo():
        return doc_repo

    def _tx_repo():
        return tx_repo

    def _insight_repo():
        return insight_repo_inst

    def _file_storage():
        return fake_file_storage

    def _parser_factory():
        return FakeParserFactory()

    app.dependency_overrides[get_user_repo] = _user_repo
    app.dependency_overrides[get_document_repo] = _doc_repo
    app.dependency_overrides[get_transaction_repo] = _tx_repo
    app.dependency_overrides[get_insight_repo] = _insight_repo
    app.dependency_overrides[get_file_storage] = _file_storage
    app.dependency_overrides[get_parser_factory] = _parser_factory

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ── Health ────────────────────────────────────────────────────────────────────


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ── Users ─────────────────────────────────────────────────────────────────────


def test_create_user(client: TestClient) -> None:
    response = client.post("/users", json={"name": "Alice"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Alice"
    assert "id" in data


def test_list_users(client: TestClient) -> None:
    client.post("/users", json={"name": "Alice"})
    client.post("/users", json={"name": "Bob"})
    response = client.get("/users")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_user_not_found(client: TestClient) -> None:
    response = client.get(f"/users/{uuid4()}")
    assert response.status_code == 404


def test_create_user_empty_name_rejected(client: TestClient) -> None:
    response = client.post("/users", json={"name": ""})
    assert response.status_code == 422


# ── Documents ─────────────────────────────────────────────────────────────────


def test_upload_document(client: TestClient) -> None:
    user = client.post("/users", json={"name": "Alice"}).json()
    response = client.post(
        "/documents/upload",
        data={"user_id": user["id"], "document_type": "bank_statement"},
        files={"file": ("statement.pdf", b"%PDF-fake", "application/pdf")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["transactions_extracted"] == 1
    assert data["document"]["filename"] == "statement.pdf"


def test_upload_duplicate_rejected(client: TestClient) -> None:
    user = client.post("/users", json={"name": "Alice"}).json()
    content = b"%PDF-unique-content"
    for _ in range(2):
        response = client.post(
            "/documents/upload",
            data={"user_id": user["id"]},
            files={"file": ("statement.pdf", content, "application/pdf")},
        )
    assert response.status_code == 409


def test_upload_unsupported_type_rejected(client: TestClient) -> None:
    user = client.post("/users", json={"name": "Alice"}).json()
    response = client.post(
        "/documents/upload",
        data={"user_id": user["id"]},
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415


def test_list_documents(client: TestClient) -> None:
    user = client.post("/users", json={"name": "Alice"}).json()
    client.post(
        "/documents/upload",
        data={"user_id": user["id"]},
        files={"file": ("s.pdf", b"%PDF-1", "application/pdf")},
    )
    response = client.get(f"/documents?user_id={user['id']}")
    assert response.status_code == 200
    assert len(response.json()) == 1


# ── Transactions ──────────────────────────────────────────────────────────────


def test_list_transactions_after_upload(client: TestClient) -> None:
    user = client.post("/users", json={"name": "Alice"}).json()
    client.post(
        "/documents/upload",
        data={"user_id": user["id"]},
        files={"file": ("s.pdf", b"%PDF-1", "application/pdf")},
    )
    response = client.get(f"/transactions?user_id={user['id']}&year=2024&month=1")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["description"] == "Lidl Supermarket"


def test_patch_transaction_category(client: TestClient) -> None:
    user = client.post("/users", json={"name": "Alice"}).json()
    client.post(
        "/documents/upload",
        data={"user_id": user["id"]},
        files={"file": ("s.pdf", b"%PDF-1", "application/pdf")},
    )
    txs = client.get(f"/transactions?user_id={user['id']}&year=2024&month=1").json()
    tx_id = txs[0]["id"]

    response = client.patch(f"/transactions/{tx_id}", json={"category": "dining"})
    assert response.status_code == 200
    assert response.json()["category"] == "dining"


def test_patch_transaction_not_found(client: TestClient) -> None:
    response = client.patch(f"/transactions/{uuid4()}", json={"category": "dining"})
    assert response.status_code == 404


def test_delete_transaction(client: TestClient) -> None:
    user = client.post("/users", json={"name": "Alice"}).json()
    client.post(
        "/documents/upload",
        data={"user_id": user["id"]},
        files={"file": ("s.pdf", b"%PDF-1", "application/pdf")},
    )
    txs = client.get(f"/transactions?user_id={user['id']}&year=2024&month=1").json()
    tx_id = txs[0]["id"]

    assert client.delete(f"/transactions/{tx_id}").status_code == 204
    txs_after = client.get(f"/transactions?user_id={user['id']}&year=2024&month=1").json()
    assert len(txs_after) == 0


# ── Health ────────────────────────────────────────────────────────────────────


def test_health_version(client: TestClient) -> None:
    response = client.get("/health")
    assert "version" in response.json()
