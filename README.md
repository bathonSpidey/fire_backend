# First time — creates the db/fire.db and runs all migrations
uv run alembic upgrade head

# After you change an ORM model — generates a new migration file
uv run alembic revision --autogenerate -m "describe_your_change"
uv run alembic upgrade head

# Check current version
uv run alembic current

# Roll back one migration
uv run alembic downgrade -1