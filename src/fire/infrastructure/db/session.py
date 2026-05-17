

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.fire.domain.entities.storage_config import StorageConfig
from src.fire.infrastructure.db.models import Base


def build_engine(storage_config: StorageConfig):  # type: ignore[no-untyped-def]
    storage_config.ensure_directories()
    db_url = f"sqlite:///{storage_config.db_path}"
    return create_engine(db_url, connect_args={"check_same_thread": False})


def build_session_factory(storage_config: StorageConfig) -> sessionmaker[Session]:
    engine = build_engine(storage_config)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def build_test_session_factory() -> sessionmaker[Session]:
    """In-memory SQLite for integration tests — fast and isolated."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
