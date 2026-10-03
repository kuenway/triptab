"""Explicit engine and session factory construction."""

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL operations")
    return url


def make_engine(url: str | None = None) -> Engine:
    selected = url or database_url()
    parsed = make_url(selected)
    if parsed.drivername != "postgresql+psycopg" or not parsed.database:
        raise ValueError("database URL must use postgresql+psycopg and name a database")
    return create_engine(selected, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
