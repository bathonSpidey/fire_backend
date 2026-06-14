from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./bank_statements.db"

# connect_args={"check_same_thread": False} is required exclusively for SQLite in FastAPI
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency provider to inject DB sessions into routes cleanly."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
