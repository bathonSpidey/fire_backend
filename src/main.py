from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.bank_statement import router as bank_statement_router
from routes.bank_statement_management import router as bank_statement_management_router
from routes.stats import router as stats_router

app = FastAPI(
    title="Bank Statement Parser API",
    description="Clean Architecture API to extract structured data from statement PDFs.",
    version="1.0.0",
)

# 1. Mount System Middlewares (e.g., CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this to specific domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Register Domain Feature Routers
app.include_router(bank_statement_router)
app.include_router(bank_statement_management_router)
app.include_router(stats_router)


@app.get("/health", tags=["System"])
async def health_check():
    """Simple application health checkpoint."""
    return {"status": "healthy"}
