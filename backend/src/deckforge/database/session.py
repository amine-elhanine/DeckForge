"""Async engine/session management.

SQLite is the default for lightweight local use; PostgreSQL is a drop-in swap via
``DECKFORGE_DATABASE_URL``. Schema creation uses ``create_all`` so a fresh clone
runs with zero migration steps — production deployments layer Alembic on top.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from deckforge.config import Settings
from deckforge.core.logging import get_logger
from deckforge.database.base import Base

log = get_logger(__name__)


class Database:
    """Owns the engine and the session factory for the process."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine = self._create_engine(settings)
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False, autoflush=False
        )

    @staticmethod
    def _create_engine(settings: Settings) -> AsyncEngine:
        url = settings.database_url
        kwargs: dict[str, Any] = {"echo": False, "future": True}
        if url.startswith("sqlite"):
            # Ensure the parent directory exists before SQLite tries to open the file.
            raw = url.split("///", 1)[-1]
            if raw and raw != ":memory:":
                Path(raw).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        else:
            kwargs |= {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True}

        engine = create_async_engine(url, **kwargs)

        if url.startswith("sqlite"):

            @event.listens_for(engine.sync_engine, "connect")
            def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

        return engine

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker

    async def create_all(self) -> None:
        """Create any missing tables."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("database.ready", url=self._settings.database_url.split("://", 1)[0])

    async def ping(self) -> bool:
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # pragma: no cover - health probe
            log.warning("database.ping_failed", error=str(exc))
            return False

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session that commits on success and rolls back on error."""
        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        await self._engine.dispose()
