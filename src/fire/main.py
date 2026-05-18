from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.fire.api.routers import documents, health, insights, transactions, users

app = FastAPI(
    title="FIRE — Financial Independence, Retire Early",
    description="Local-first personal finance manager with AI document extraction.",
    version="0.1.0",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Allow the Vite dev server and any LAN device to reach the API.
# In production (Docker) the frontend origin is the LAN IP or fire.local.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # alternative dev port
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"http://192\.168\.\d+\.\d+(:\d+)?",  # any LAN device
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(users.router)
app.include_router(documents.router)
app.include_router(transactions.router)
app.include_router(insights.router)
