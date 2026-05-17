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
8. [How the layers talk to each other](#how-the-layers-talk-to-each-other)
9. [Key design decisions](#key-design-decisions)
10. [What has been built so far](#what-has-been-built-so-far)
11. [What is coming next](#what-is-coming-next)

---

## What this app does

- Upload a PDF bank statement, investment statement, or a photo of a receipt
- The AI (running locally via Ollama) reads the document and extracts all transactions
- Transactions are stored in a local SQLite database
- At the end of the month, ask for insights — the AI summarises your spending,
  calculates your savings rate, and gives you tips tailored to your FIRE goals
- Two users (e.g. you and your partner) each have their own data, selected by
  profile on the front end — no passwords, no login, this is a home network app

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.12, FastAPI |
| Database | SQLite + SQLAlchemy ORM + Alembic migrations |
| AI / LLM | Ollama running locally (llava:13b for vision, mistral:7b for text) |
| File storage | Local filesystem (root/files/DD-MM/) |
| Package manager | uv |
| Testing | pytest + pytest-asyncio |
| Frontend (coming) | Vite + React + TypeScript |
| Deployment (coming) | Docker Compose |

---

## Project structure

```
fire_backend/
│
├── alembic/                    # Database migration files
│   ├── env.py                  # Alembic configuration — connects to SQLite
│   └── versions/               # One file per migration (auto-generated)
│       └── xxxx_initial_schema.py
│
├── db/                         # SQLite database lives here (git-ignored)
│   └── fire.db
│
├── src/
│   └── fire/
│       ├── domain/             # innermost layer, zero dependencies
│       │   ├── entities/       # Pure Python dataclasses — the core objects
│       │   │   ├── user.py
│       │   │   ├── document.py
│       │   │   ├── transaction.py
│       │   │   ├── account.py
│       │   │   ├── budget_insight.py
│       │   │   └── storage_config.py
│       │   └── interfaces/     # Abstract contracts (ABCs) — no implementations
│       │       ├── repositories.py
│       │       └── services.py
│       │
│       ├── application/        # Business logic — uses interfaces, not implementations
│       │   └── use_cases/
│       │       ├── ingest_document.py
│       │       ├── extract_transactions.py
│       │       ├── get_monthly_summary.py
│       │       └── generate_insights.py
│       │
│       ├── infrastructure/     # Concrete implementations — hits real disk/DB/LLM
│       │   ├── db/
│       │   │   ├── models.py   # SQLAlchemy ORM table definitions
│       │   │   └── session.py  # Engine + session factory
│       │   ├── repositories/   # SQLite implementations of domain interfaces
│       │   │   ├── user_repository.py
│       │   │   ├── document_repository.py
│       │   │   ├── transaction_repository.py
│       │   │   └── account_insight_repositories.py
│       │   ├── llm/
│       │   │   ├── ollama_document_parser.py   # Vision model — reads PDFs/images
│       │   │   └── ollama_insight_generator.py # Text model — monthly analysis
│       │   └── file_storage/
│       │       └── local_file_storage.py       # Saves uploads to root/files/DD-MM/
│       │
│       └── api/                # FastAPI routers and schemas (coming in Step 5)
│
├── tests/
│   ├── fakes.py                # In-memory fakes for every interface
│   ├── unit/
│   │   ├── domain/             # Tests for entities — pure logic, no I/O
│   │   └── application/        # Tests for use cases — fakes injected
│   └── integration/            # Tests against real SQLite and real disk
│
├── alembic.ini                 # Alembic config file
└── pyproject.toml              # Project dependencies and tool config
```

---

## Architecture — the big picture

This project follows **Clean Architecture** (Uncle Bob).
The most important rule is the **dependency rule**:

```
Domain  <-  Application  <-  Infrastructure  <-  API  <-  Frontend
```

Inner layers know nothing about outer layers.
The domain has no idea SQLite or Ollama exist.
The application layer only talks to interfaces — never to SQLAlchemy or httpx directly.

```
+-------------------------------------------+
|           Frontend  (React)               |
+-------------------------------------------+
|           API Layer (FastAPI)             |
+-------------------------------------------+
|        Application (Use Cases)            |  <- pure business logic
+-------------------------------------------+
|    Domain  (Entities + Interfaces)        |  <- zero dependencies
+---------------+----------+----------------+
|  Repositories |   LLM    |  File Storage  |  <- infrastructure
|  (SQLite)     | (Ollama) |  (local disk)  |
+---------------+----------+----------------+
```

**Why does this matter?**
If you want to swap SQLite for PostgreSQL tomorrow, you only touch the infrastructure
layer. The use cases and domain entities do not change at all. Same for swapping
Ollama for a different model — one class changes, nothing else breaks.

---

## Getting started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — install with `pip install uv`
- [Ollama](https://ollama.com) installed and running
- Git

### 1. Clone and install

```bash
git clone <your-repo-url>
cd fire_backend

# Install all dependencies into a virtual environment
uv sync

# Install the package itself in editable mode
uv pip install -e .
```

### 2. Pull the Ollama models

You need two models. With 12GB VRAM these both fit comfortably:

```bash
# Vision model — reads PDFs and screenshots
ollama pull llava:13b

# Text model — generates monthly insights
ollama pull mistral:7b-instruct
```

Make sure Ollama is running before you start the backend:

```bash
ollama serve
```

### 3. Set up the database

```bash
# Create the db/ directory
mkdir db

# Run migrations — this creates db/fire.db with all tables
uv run alembic upgrade head
```

You should see:
```
INFO  [alembic.runtime.migration] Running upgrade  -> xxxx, initial_schema
```

### 4. Verify everything works

```bash
uv run pytest
```

All 99 tests should pass.

### 5. Start the backend (coming in Step 5)

```bash
uv run uvicorn fire.main:app --reload
```

---

## Running the tests

```bash
# Run everything
uv run pytest

# Run only unit tests (fast, no disk or LLM needed)
uv run pytest tests/unit/

# Run only integration tests (real SQLite in-memory + real disk)
uv run pytest tests/integration/

# Run with coverage report
uv run pytest --cov=src/fire
```

The test suite is split into two clear buckets:

**Unit tests** — milliseconds each, zero I/O.
Use cases and entities are tested with hand-rolled in-memory fakes.
No database, no files, no Ollama required.

**Integration tests** — slightly slower, real I/O.
Repositories tested against real in-memory SQLite (wiped after each test).
File storage tested against a real temporary directory.
Still no Ollama required — LLM tests cover parsing logic only.

---

## Database migrations

Alembic tracks every schema change as a versioned migration file.
Think of it like Git for your database structure.

```bash
# Apply all pending migrations (run this after pulling new code)
uv run alembic upgrade head

# Check which migration version you are on
uv run alembic current

# After changing an ORM model, generate a new migration automatically
uv run alembic revision --autogenerate -m "describe_your_change"
uv run alembic upgrade head

# Roll back one migration if something went wrong
uv run alembic downgrade -1
```

The database lives at db/fire.db. Add db/ to your .gitignore —
never commit the database itself, only the migration files.

---

## How the layers talk to each other

Here is the journey of a single uploaded bank statement end to end:

```
1. User uploads january_statement.pdf via the frontend

2. API layer receives the file bytes
   -> calls IngestDocument use case

3. IngestDocument (application layer):
   -> computes SHA-256 hash of the file bytes
   -> checks IDocumentRepository — is this a duplicate?
   -> calls IFileStorage.save() -> file written to root/files/15-01/january_statement.pdf
   -> creates a Document entity (status: PENDING)
   -> saves it via IDocumentRepository
   -> returns the Document

4. API layer then calls ExtractTransactions use case

5. ExtractTransactions (application layer):
   -> reads the file bytes back via IFileStorage.read()
   -> calls ILLMDocumentParser.parse() -> Ollama llava:13b reads the PDF
   -> maps each extracted transaction to a Transaction entity
   -> saves them all via ITransactionRepository.save_batch()
   -> marks the Document as PROCESSED
   -> returns the list of transactions

6. Later — user requests monthly insights:
   -> GetMonthlySummary aggregates transactions for that month
   -> GenerateInsights calls ILLMInsightGenerator -> Ollama mistral:7b
   -> BudgetInsight entity created and persisted
   -> returned to the frontend
```

---

## Key design decisions

**Why SQLite and not PostgreSQL?**
This is a local home app for two people. SQLite is zero-config, single-file,
and trivially backed up. You can always migrate to PostgreSQL later — the
repository interfaces mean the use cases will not change at all.

**Why two Ollama models?**
llava:13b is a vision model that can read images and PDFs.
mistral:7b-instruct is a text-only model — faster for generating prose where
no image is needed. Both run in 12GB VRAM because they are not loaded simultaneously.

**Why no passwords?**
This app runs on your home LAN. Only devices on your network can reach it.
A profile selector is sufficient. A PIN can be added later without touching
any business logic.

**Why are ORM models separate from domain entities?**
SQLAlchemy ORM objects carry session state and lazy-loading behaviour.
Domain entities are plain dataclasses — simple, predictable, testable without
a database. The repository translates between the two.

**Why hand-rolled fakes instead of unittest.mock?**
Fakes implement the real interface contract. If you rename a method on the
interface, the fake breaks immediately at instantiation — instant feedback.
Mocks break silently at runtime and are tied to implementation details.

---

## What has been built so far

| Step | What | Status |
|------|------|--------|
| 1 | Domain entities + interfaces | Done |
| 2 | Application use cases | Done |
| 3 | SQLite repositories + Alembic + multi-user | Done |
| 4 | Ollama LLM adapters + local file storage | Done |
| 5 | FastAPI routers + dependency injection | Next |
| 6 | Docker Compose for local deployment | Planned |
| 7 | React + Vite frontend | Planned |

**Test count: 99 passing, 0 failing.**

---

## What is coming next

**Step 5 — FastAPI API layer**

Endpoints being built:
- POST /users — create a profile
- GET /users — list profiles (for the profile selector)
- POST /documents/upload — upload PDF or image, triggers ingestion + extraction
- GET /documents — list documents for a user
- GET /transactions — list transactions for a user and month
- POST /insights/generate — generate monthly insight for a user
- GET /insights — get saved insight for a user and month

**Step 6 — Docker Compose**
- fire-backend container with volume mounts for db/ and files/
- ollama container with GPU passthrough for your RTX card
- Configured to auto-start so every device on your LAN has access

**Step 7 — React frontend**
- Profile selector (you vs your partner)
- Upload screen with drag-and-drop
- Transaction list with category filters
- Monthly dashboard — income, expenses, savings rate, FIRE progress tracker
- Insights panel with LLM-generated tips



# First time — creates the db/fire.db and runs all migrations
uv run alembic upgrade head

# After you change an ORM model — generates a new migration file
uv run alembic revision --autogenerate -m "describe_your_change"
uv run alembic upgrade head

# Check current version
uv run alembic current

# Roll back one migration
uv run alembic downgrade -1