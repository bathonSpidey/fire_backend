# 🔥 FIRE — Financial Independence, Retire Early

A local-first personal finance manager that uses AI to read your bank statements,
receipts, and investment reports — then gives you monthly insights to help you
reach financial independence faster.

Everything runs on your own machine. Your financial data never leaves your network.

---

## Table of Contents

1. [What this app does](#what-this-app-does)
2. [Tech stack](#tech-stack)
3. [Project structure](#project-structure)
4. [Architecture — the big picture](#architecture--the-big-picture)
5. [Getting started](#getting-started)
6. [Running the tests](#running-the-tests)
7. [Database migrations](#database-migrations)
8. [API reference](#api-reference)
9. [Document parsing — how it works](#document-parsing--how-it-works)
10. [How the layers talk to each other](#how-the-layers-talk-to-each-other)
11. [Key design decisions](#key-design-decisions)
12. [What has been built](#what-has-been-built)
13. [What is coming next](#what-is-coming-next)

---

## What this app does

- Upload a PDF bank statement, investment statement, or a photo of a receipt
- PDFs are parsed locally using rules-based text extraction — free, accurate, private
- Image receipts are read by a cloud vision AI (Gemini or Claude) and returned as structured data
- All transactions are stored in a local SQLite database
- Users can correct any extraction errors directly in the app
- At the end of the month, an LLM generates a personalised financial summary with FIRE-focused tips
- Two users (e.g. you and your partner) each have their own data — no passwords, just profile selection

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.12, FastAPI |
| Database | SQLite + SQLAlchemy ORM + Alembic migrations |
| PDF parsing | PyMuPDF — local, free, no API key needed |
| Receipt parsing | Google Gemini or Anthropic Claude via direct REST calls (httpx) |
| Insight generation | Ollama (local LLM — qwen3 or similar) |
| Package manager | uv |
| Testing | pytest + pytest-asyncio |
| Frontend (coming) | Vite + React + TypeScript |
| Deployment (coming) | Docker Compose |

---

## Project structure

```
fire_backend/
│
├── alembic/                         # Database migration files
│   ├── env.py                       # Alembic config — reads FIRE_DB_PATH or default
│   └── versions/
│       └── xxxx_initial_schema.py   # First migration — all 5 tables
│
├── db/                              # SQLite database (git-ignored)
│   └── fire.db
│
├── src/
│   └── fire/
│       ├── config/
│       │   └── settings.py          # Pydantic BaseSettings — reads from .env
│       │
│       ├── domain/                  # Innermost layer — zero dependencies
│       │   ├── entities/
│       │   │   ├── user.py          # Household member (no password)
│       │   │   ├── document.py      # Uploaded file with status lifecycle
│       │   │   ├── transaction.py   # Single financial record
│       │   │   ├── account.py       # Bank or investment account
│       │   │   ├── budget_insight.py # LLM monthly analysis
│       │   │   └── storage_config.py # Path value object (files/ and db/)
│       │   └── interfaces/
│       │       ├── repositories.py  # IUserRepo, IDocumentRepo, etc.
│       │       └── services.py      # ILLMDocumentParser, IFileStorage, etc.
│       │
│       ├── application/             # Business logic — no frameworks
│       │   └── use_cases/
│       │       ├── ingest_document.py       # Hash, dedup, store, create Document
│       │       ├── extract_transactions.py  # Parse file, map to entities, persist
│       │       ├── get_monthly_summary.py   # Aggregate transactions by month
│       │       └── generate_insights.py     # Call LLM, persist BudgetInsight
│       │
│       ├── infrastructure/          # Concrete implementations
│       │   ├── db/
│       │   │   ├── models.py        # SQLAlchemy ORM models (separate from entities)
│       │   │   └── session.py       # Engine + sessionmaker factory
│       │   ├── repositories/
│       │   │   ├── user_repository.py
│       │   │   ├── document_repository.py
│       │   │   ├── transaction_repository.py
│       │   │   └── account_insight_repositories.py
│       │   ├── llm/
│       │   │   ├── pdf_text_parser.py        # Local rules-based PDF parser
│       │   │   ├── gemini_document_parser.py # Gemini REST API via httpx
│       │   │   ├── claude_document_parser.py # Claude REST API via httpx
│       │   │   ├── ollama_document_parser.py # Local Ollama (experimental)
│       │   │   ├── ollama_insight_generator.py # Monthly insight via local LLM
│       │   │   └── document_parser_factory.py  # Routes to correct parser
│       │   └── file_storage/
│       │       └── local_file_storage.py     # Saves to root/files/DD-MM/
│       │
│       ├── api/
│       │   ├── main.py              # FastAPI app — CORS + router mounting only
│       │   ├── dependencies.py      # Depends() wiring for all repos and use cases
│       │   ├── routes/
│       │   │   ├── health.py        # GET /health
│       │   │   ├── users.py         # POST/GET /users
│       │   │   ├── documents.py     # POST /documents/upload, GET /documents
│       │   │   ├── transactions.py  # GET/PATCH/DELETE /transactions
│       │   │   └── insights.py      # POST /insights/generate, GET /insights
│       │   └── schemas/
│       │       ├── user.py
│       │       ├── document.py
│       │       ├── transaction.py
│       │       └── insight.py
│       │
│       └── main.py                  # Entry point — imports api/main.py app
│
├── tests/
│   ├── fakes.py                     # In-memory fakes for every interface
│   ├── unit/
│   │   ├── domain/                  # Entity logic — zero I/O
│   │   ├── application/             # Use case logic — fakes injected
│   │   └── infrastructure/          # Parser/settings/factory unit tests
│   └── integration/
│       ├── test_repositories.py     # Real SQLite in-memory
│       ├── test_file_storage.py     # Real temp directory
│       ├── test_api.py              # TestClient + shared-memory SQLite
│       ├── test_live_llm.py         # Real Gemini API (marked live, skipped by default)
│       └── data/                    # Real fixture files (git-ignored)
│
├── scripts/
│   └── diagnose_llm.py              # Dev tool — test model output on real files
│
├── .env.example                     # Copy to .env and fill in your keys
├── alembic.ini
└── pyproject.toml
```

---

## Architecture — the big picture

This project follows **Clean Architecture** (Uncle Bob).
The most important rule is the **dependency rule**:

```
Domain  ←  Application  ←  Infrastructure  ←  API  ←  Frontend
```

Inner layers know nothing about outer layers.
The domain has no idea SQLite, Gemini, or FastAPI exist.
The application layer only talks to interfaces — never to SQLAlchemy or httpx directly.

```
┌──────────────────────────────────────────────┐
│              Frontend  (React)               │
├──────────────────────────────────────────────┤
│          API Layer  (FastAPI routes)         │
├──────────────────────────────────────────────┤
│        Application  (Use Cases)              │  ← pure business logic
├──────────────────────────────────────────────┤
│    Domain  (Entities + Interfaces)           │  ← zero dependencies
├─────────────────┬────────────┬───────────────┤
│   Repositories  │    LLM     │  File Storage │  ← infrastructure
│   (SQLite)      │(Gemini/PDF)│  (local disk) │
└─────────────────┴────────────┴───────────────┘
```

Adding a new receipt provider (e.g. OpenAI):
1. Create `OpenAIDocumentParser(ILLMDocumentParser)` in `infrastructure/llm/`
2. Add `OPENAI = "openai"` to `ReceiptProvider` enum in `settings.py`
3. Add one `elif` branch in `DocumentParserFactory._build_image_parser()`
4. Done — nothing else changes

---

## Getting started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — `pip install uv`
- Git

### 1. Clone and install

```bash
git clone <your-repo-url>
cd fire_backend
uv sync
uv pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in at minimum:

```dotenv
FIRE_DATA_ROOT=C:/Users/YourName/fire-data   # where files and db are stored
GEMINI_API_KEY=AIza...                        # for reading image receipts
```

### 3. Set up the database

```bash
mkdir db
uv run alembic upgrade head
```

### 4. Start the server

```bash
uv run uvicorn fire.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs` for the interactive API documentation.

---

## Running the tests

```bash
# Run everything (fast tests only — no API calls, no Ollama)
uv run pytest

# Unit tests only
uv run pytest tests/unit/

# Integration tests (real SQLite, real disk, no API keys needed)
uv run pytest tests/integration/ -m "not live"

# Live tests — requires GEMINI_API_KEY in .env and real fixture files
uv run pytest -m live -v -s

# With coverage
uv run pytest --cov=src/fire
```

**Test layout:**

| Folder | What it tests | Needs |
|---|---|---|
| `tests/unit/domain/` | Entity logic and invariants | Nothing |
| `tests/unit/application/` | Use case logic | In-memory fakes |
| `tests/unit/infrastructure/` | Parser, settings, factory logic | Nothing |
| `tests/integration/test_repositories.py` | SQL queries against SQLite | In-memory SQLite |
| `tests/integration/test_file_storage.py` | File read/write | Temp directory |
| `tests/integration/test_api.py` | HTTP routes end-to-end | Shared-memory SQLite |
| `tests/integration/test_live_llm.py` | Real Gemini + real receipts | GEMINI_API_KEY + fixture files |

**153 tests, all green (8 live tests deselected by default).**

---

## Database migrations

```bash
# Apply all pending migrations (run after pulling new code)
uv run alembic upgrade head

# Check current version
uv run alembic current

# Generate a new migration after changing an ORM model
uv run alembic revision --autogenerate -m "describe_your_change"
uv run alembic upgrade head

# Roll back one migration
uv run alembic downgrade -1
```

Never edit migration files by hand. Never commit `db/fire.db`.

---

## API reference

Full interactive docs at `http://localhost:8000/docs` when the server is running.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/users` | Create a user profile |
| GET | `/users` | List all profiles (for profile selector) |
| GET | `/users/{id}` | Get a single user |
| POST | `/documents/upload` | Upload PDF or image — triggers extract pipeline |
| GET | `/documents?user_id=` | List documents for a user |
| GET | `/documents/{id}` | Get a single document |
| GET | `/transactions?user_id=&year=&month=` | List transactions for a month |
| GET | `/transactions/{id}` | Get a single transaction |
| PATCH | `/transactions/{id}` | Correct a transaction (amount, category, type) |
| DELETE | `/transactions/{id}` | Delete a transaction |
| POST | `/insights/generate?user_id=&year=&month=` | Generate monthly insight via LLM |
| GET | `/insights?user_id=&year=&month=` | Get saved insight |
| GET | `/insights/history?user_id=` | List insight history |

---

## Document parsing — how it works

FIRE uses a two-track parsing strategy:

**PDFs (bank statements, investment reports)**
Text is extracted directly from the PDF using PyMuPDF. No API call, no network, completely free. A rules-based parser finds transaction rows anchored by `DD.MM.YYYY` date patterns, detects Soll/Haben columns for debit/credit direction, and classifies by keyword matching. Supports Sparkasse and most German bank formats.

**Image receipts (photos, screenshots)**
The image is base64-encoded and sent to the configured vision API. Gemini `gemini-2.5-flash` is the recommended default — fast, cheap, and accurate for German receipts. Claude is available as an alternative. The response is always structured JSON.

**Changing provider = one line in `.env`:**
```dotenv
FIRE_RECEIPT_PROVIDER=gemini   # or: claude, ollama
GEMINI_API_KEY=AIza...
```

---

## How the layers talk to each other

Upload pipeline for a bank statement PDF:

```
1. POST /documents/upload (multipart form: file + user_id)

2. IngestDocument use case:
   → SHA-256 hash of file bytes
   → Reject if duplicate (same hash already exists)
   → Save file to  data/files/DD-MM/filename.pdf
   → Create Document entity (status: PENDING)
   → Persist via IDocumentRepository

3. ExtractTransactions use case:
   → DocumentParserFactory.get_parser_for_mime("application/pdf")
     returns PdfTextParser (local, no API call)
   → PdfTextParser.parse() → extracts text → regex finds transactions
   → Each row mapped to Transaction entity
   → Batch saved via ITransactionRepository
   → Document marked PROCESSED

4. Response: { document: {...}, transactions_extracted: 12 }
```

User corrects a salary entry misclassified as debit:

```
PATCH /transactions/{id}
Body: { "transaction_type": "credit", "category": "income" }

→ TransactionRepository.get_by_id()
→ Apply only the provided fields
→ TransactionRepository.save()
→ Return updated transaction
```

---

## Key design decisions

**Why SQLite?**
Zero-config, single file, trivially backed up. Supports two users on a home LAN without any issue. Can be swapped for PostgreSQL by changing the connection string — the repository interfaces mean no use case code changes.

**Why no SDK for Gemini or Claude?**
Both `google-generativeai` and `anthropic` SDKs carry transitive dependencies with a history of CVEs. We call the REST APIs directly via `httpx`, which is already in the dependency tree and is a well-audited, single-purpose HTTP client.

**Why rules-based PDF parsing instead of LLM for PDFs?**
PDFs with selectable text (all major German banks) give you 100% accuracy for free. LLMs are probabilistic — fine for images where there is no better option, but unnecessary and slower for structured text.

**Why hand-rolled fakes instead of `unittest.mock`?**
Fakes implement the real interface. Rename a method on the interface and the fake breaks at import time — instant feedback. Mocks break silently at runtime and are tied to implementation details.

**Why no passwords?**
This is a home LAN app. Only devices on your network can reach it. A profile selector is sufficient. A PIN can be added in 30 minutes without touching any business logic.

---

## What has been built

| Step | What | Status |
|---|---|---|
| 1 | Domain entities + interfaces | ✅ Done |
| 2 | Application use cases | ✅ Done |
| 3 | SQLite repositories + Alembic + multi-user | ✅ Done |
| 4 | PDF rules-based parser + Gemini/Claude image parsers + local file storage | ✅ Done |
| 5 | FastAPI routes + schemas + dependency injection | ✅ Done |
| 6 | Docker Compose — local deployment | 🔜 Next |
| 7 | React + Vite frontend | 🔜 Planned |

**153 tests passing. 0 failing.**

---

## What is coming next

### Step 6 — Docker Compose

```yaml
services:
  fire-backend:
    build: .
    ports: ["8000:8000"]
    volumes:
      - ./data:/app/data     # db/ and files/ persist between restarts
    env_file: .env

  ollama:
    image: ollama/ollama
    volumes:
      - ollama_models:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

Auto-starts with Docker Desktop "start on login". Every device on your LAN reaches the app at `http://fire.local` or `http://192.168.x.x:8000`.

### Step 7 — React + Vite frontend

- Profile selector — choose between your two accounts
- Upload screen — drag and drop PDF or receipt image
- Transaction list — grouped by month, editable inline
- Monthly dashboard — income vs expenses, savings rate, FIRE progress bar
- Insights panel — LLM summary and tips for the selected month