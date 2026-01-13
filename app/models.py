from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from arcanus.base import TransmuterProxiedMixin
from sqlalchemy import DateTime, Integer, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase, TransmuterProxiedMixin):
    """Base class for all ORM models."""

    pass


class Message(Base):
    """Simple message table for storing chat messages."""

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.uuidv7()
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    group_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "Base",
    "Message",
]
