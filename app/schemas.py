from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from arcanus.base import BaseTransmuter, Identity
from arcanus.materia.sqlalchemy import SqlalchemyMateria
from pydantic import Field

from app.models import Message as MessageORM

# Initialize SQLAlchemy Materia for blessing
sqlalchemy_materia = SqlalchemyMateria()

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _now_shanghai() -> datetime:
    return datetime.now(SHANGHAI_TZ)


@sqlalchemy_materia.bless(MessageORM)
class Message(BaseTransmuter):
    """Transmuter for Message - binds to SQLAlchemy ORM."""

    id: Annotated[Optional[UUID], Identity] = Field(default=None, frozen=True)
    user_id: int
    group_id: Optional[int] = None
    kind: Literal["request", "response"]
    content: str
    timestamp: datetime = Field(default_factory=_now_shanghai)


__all__ = [
    "sqlalchemy_materia",
    "Message",
]
