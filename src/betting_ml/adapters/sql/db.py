"""Engine / session factory and Alembic upgrade."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect
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


def _alembic_config(url: str):  # type: ignore[no-untyped-def]
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", resolve_url(url))
    return config


def upgrade(url: str, revision: str = "head") -> None:
    """Apply Alembic migrations (``make db-upgrade``). A database created before Alembic
    (tables present, no ``alembic_version``) is stamped at the initial revision first."""
    from alembic import command

    config = _alembic_config(url)
    engine = make_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    if tables and "alembic_version" not in tables:
        command.stamp(config, "0001")
    command.upgrade(config, revision)


def prepare(url: str) -> Engine:
    """Engine ready to use: an in-memory DB gets the tables directly; a file DB is migrated."""
    from betting_ml.adapters.sql.models import Base

    if resolve_url(url) == "sqlite:///:memory:":
        engine = make_engine(url)
        Base.metadata.create_all(engine)
        return engine
    upgrade(url)
    return make_engine(url)
