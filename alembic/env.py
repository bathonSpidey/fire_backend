# import os
# from logging.config import fileConfig
# from pathlib import Path

# from alembic import context
# from sqlalchemy import engine_from_config, pool
# from src.fire.infrastructure.db.models import Base

# config = context.config
# if config.config_file_name is not None:
#     fileConfig(config.config_file_name)

# target_metadata = Base.metadata


# def get_url() -> str:
#     """
#     Build the database URL from environment variables.

#     Priority:
#     1. FIRE_DB_PATH — explicit full path to fire.db
#     2. FIRE_DATA_ROOT — root data directory, db goes in <root>/db/fire.db
#     3. Fallback — ./db/fire.db relative to current working directory
#     """
#     if db_path := os.getenv("FIRE_DB_PATH"):
#         return f"sqlite:///{db_path}"

#     if data_root := os.getenv("FIRE_DATA_ROOT"):
#         db_dir = Path(data_root) / "db"
#         db_dir.mkdir(parents=True, exist_ok=True)
#         return f"sqlite:///{db_dir / 'fire.db'}"

#     # Local development fallback
#     db_dir = Path.cwd() / "db"
#     db_dir.mkdir(parents=True, exist_ok=True)
#     return f"sqlite:///{db_dir / 'fire.db'}"


# def run_migrations_offline() -> None:
#     context.configure(
#         url=get_url(),
#         target_metadata=target_metadata,
#         literal_binds=True,
#         dialect_opts={"paramstyle": "named"},
#         render_as_batch=True,
#     )
#     with context.begin_transaction():
#         context.run_migrations()


# def run_migrations_online() -> None:
#     configuration = config.get_section(config.config_ini_section, {})
#     configuration["sqlalchemy.url"] = get_url()
#     connectable = engine_from_config(
#         configuration,
#         prefix="sqlalchemy.",
#         poolclass=pool.NullPool,
#     )
#     with connectable.connect() as connection:
#         context.configure(
#             connection=connection,
#             target_metadata=target_metadata,
#             render_as_batch=True,
#         )
#         with context.begin_transaction():
#             context.run_migrations()


# if context.is_offline_mode():
#     run_migrations_offline()
# else:
#     run_migrations_online()
