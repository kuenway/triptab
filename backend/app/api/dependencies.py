"""One SQLAlchemy session per request, created lazily from DATABASE_URL."""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from app.application.service import TripTabService
from app.persistence.database import make_engine, make_session_factory


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return make_session_factory(make_engine())


def get_session() -> Iterator[Session]:
    with _session_factory()() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def get_service(session: SessionDependency) -> TripTabService:
    return TripTabService(session)
