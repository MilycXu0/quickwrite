"""Database engine and session management."""

import logging
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.models import Base

logger = logging.getLogger(__name__)


class Database:
    """Manages SQLAlchemy engine, session factory, and schema initialization."""

    def __init__(self, db_url: str = "sqlite:///F:/novel-writer-agent/data/novels.db"):
        self.db_url = db_url

        # For SQLite, ensure the directory exists
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            # Handle Windows absolute paths like sqlite:///F:/...
            db_dir = Path(db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)

        self._engine: Engine | None = None
        self._session_factory: sessionmaker | None = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine(
                self.db_url,
                echo=False,
                connect_args={"check_same_thread": False} if "sqlite" in self.db_url else {},
            )
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        if self._session_factory is None:
            self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        return self._session_factory

    def create_session(self) -> Session:
        """Create a new database session."""
        return self.session_factory()

    def initialize(self, drop_all: bool = False) -> None:
        """Create all tables. Set drop_all=True to reset the database."""
        if drop_all:
            logger.warning("Dropping all tables!")
            Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        logger.info("Database initialized: %s", self.db_url)

    def close(self) -> None:
        """Close the database engine."""
        if self._engine:
            self._engine.dispose()
            logger.info("Database engine disposed")
