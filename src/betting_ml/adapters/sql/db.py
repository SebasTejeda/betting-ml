"""Engine / session factory and Alembic upgrade."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from betting_ml.config import PROJECT_ROOT

MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def resolve_url(url: str) -> str:
    """Relative SQLite paths are resolved against the project root."""
    prefix = "sqlite:///"
    if url.startswith(prefix) and url != "sqlite:///:memory:":
        path = Path(url[len(prefix) :])
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return prefix + path.as_posix()
    return url


def make_engine(url: str) -> Engine:
    resolved = resolve_url(url)
    kwargs: dict[str, object] = {}
    if resolved.startswith("sqlite"):
        # FastAPI runs endpoints in a thread pool; an in-memory DB must be one shared connection.
        kwargs["connect_args"] = {"check_same_thread": False}
        if resolved == "sqlite:///:memory:":
            kwargs["poolclass"] = StaticPool
    engine = create_engine(resolved, future=True, **kwargs)  # type: ignore[arg-type]
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _foreign_keys(dbapi_connection, _):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def upgrade(url: str, revision: str = "head") -> None:
    """Apply Alembic migrations (``make db-upgrade``)."""
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", resolve_url(url))
    command.upgrade(config, revision)
