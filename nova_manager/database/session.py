from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from nova_manager.core.config import DATABASE_URL
from nova_manager.core.log import logger

# Cloud SQL drops idle connections; check one before use so a job doesn't fail mid-way
# (after its ClickHouse insert, so its retry writes the events twice).
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()

    try:
        yield db
        db.commit()
    except Exception as e:
        logger.error(f"Error committing database transaction: {e}")
        db.rollback()
        raise e
    finally:
        db.close()


@contextmanager
def db_session():
    """Context manager for database sessions in background tasks"""
    return get_db()
