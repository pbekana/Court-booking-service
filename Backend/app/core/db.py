from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import DATABASE_URL

Base = declarative_base()


Engine = create_engine(DATABASE_URL) if DATABASE_URL else None
SessionLocal = (
    sessionmaker(autocommit=False, autoflush=False, bind=Engine)
    if Engine is not None
    else None
)


def get_db():
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL must be configured before using the database")

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_connection():
    if Engine is None:
        raise RuntimeError(
            "DATABASE_URL must be configured before checking the database"
        )

    with Engine.connect() as connection:
        connection.execute(text("SELECT 1"))
