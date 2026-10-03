"""Explicit engine and session factory construction."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def database_url() -> str:
    url = get_settings().database_url
    if url is None:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL operations")
    return url.get_secret_value()


def make_engine(url: str | None = None) -> Engine:
    selected = url or database_url()
    parsed = make_url(selected)
    if parsed.drivername != "postgresql+psycopg" or not parsed.database:
        raise ValueError("database URL must use postgresql+psycopg and name a database")
    return create_engine(
        selected,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
        pool_timeout=5,
        connect_args={"connect_timeout": 5},
        hide_parameters=True,
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
