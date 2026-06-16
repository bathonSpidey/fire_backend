# 1. Use an official lightweight Python image
FROM python:3.14-slim

# 2. Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

# 3. Establish the internal working directory
WORKDIR /app

# 4. Install 'uv' inside the container cleanly
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 5. Copy configuration specs first to leverage layer caching
COPY pyproject.toml uv.lock ./

# 6. Install project dependencies without creating virtualenvs globally
RUN uv sync --frozen --no-cache

# 7. Copy the rest of the application source code
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# 8. Make our custom boot script executable
RUN chmod +x ./src/entrypoint.sh

# 9. Expose port 8001 outside the container boundaries
EXPOSE 8001

# 10. Hand execution over to our custom entrypoint script
ENTRYPOINT ["./src/entrypoint.sh"]