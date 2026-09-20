from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from database.migrate import refresh_derived_data, upgrade_to_head
from routes.auth import claude_router, require_login
from routes.auth import router as auth_router
from routes.bank_statement_management import router as bank_statement_management_router
from routes.categories import router as categories_router
from routes.documents import router as documents_router
from routes.entries import router as entries_router
from routes.inventory_analysis import router as inventory_analysis_router
from routes.inventory_management import router as inventory_management_router
from routes.reviews import router as reviews_router
from routes.spending import router as spending_router
from routes.stats import router as stats_router
from routes.stock import router as stock_router
from services import ingest_worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    upgrade_to_head()
    refresh_derived_data()
    ingest_worker.start()
    yield
    ingest_worker.stop()


# The interactive API docs would show every endpoint to anyone on the network: development only.
app = FastAPI(
    title="Bank Statement Parser API",
    description="Clean Architecture API to extract structured data from statement PDFs.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
)

# Everything the app does lives under /api and needs the household PIN, except signing in.
# The frontend is served from the same address, so no cross-origin access is allowed at all.
api = APIRouter(prefix="/api")
api.include_router(auth_router)

protected = APIRouter(dependencies=[Depends(require_login)])
for router in (
    bank_statement_management_router, stats_router, inventory_management_router, inventory_analysis_router,
    documents_router, reviews_router, categories_router, entries_router, stock_router, spending_router,
    claude_router,
):
    protected.include_router(router)
api.include_router(protected)
app.include_router(api)


@app.get("/api/health", tags=["System"])
async def health_check():
    """Simple application health checkpoint."""
    return {"status": "healthy"}


# The built frontend (npm run build) is served by this same process: one address for every device.
_dist = settings.FIRE_FRONTEND_DIST.resolve()
if (_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "No such endpoint.")
        file = (_dist / path).resolve()
        if path and file.is_file() and _dist in file.parents:  # favicon, icons; never outside the folder
            return FileResponse(file)
        return FileResponse(_dist / "index.html", headers={"Cache-Control": "no-cache"})
