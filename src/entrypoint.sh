#!/bin/sh

# Exit immediately if a command exits with a non-zero status
set -e

echo "Executing database migrations..."
# Run alembic to upgrade your SQLite DB layout to the latest version
uv run alembic upgrade head

echo "Database is ready. Starting FastAPI Server..."
# Launch Uvicorn bound to port 8001
exec uv run uvicorn main:app --host 0.0.0.0 --port 8001