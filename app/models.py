from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from arcanus.base import TransmuterProxiedMixin
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class DateTimeAwareJSONB(TypeDecorator):
    """Custom JSONB type that handles datetime serialization."""

    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Serialize datetime objects to ISO format strings before storing."""
        if value is None:
            return value

        def serialize(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: serialize(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [serialize(item) for item in obj]
            return obj

        return serialize(value)


class Base(DeclarativeBase, TransmuterProxiedMixin):
    """Base class for all ORM models."""

    pass


class Message(Base):
    """Simple message table for storing chat messages."""

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.uuidv7()
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModelMessage(Base):
    """
    Parent ORM model for detailed model messages (joined table inheritance).

    This table contains common fields shared between requests and responses.
    Both ModelRequest and ModelResponse use joined table inheritance.
    """

    __tablename__ = "model_messages"
    __table_args__ = (
        Index("ix_model_messages_user_group_id", "id", "user_id", "group_id"),
        Index(
            "ix_model_messages_user_group_run_id", "id", "user_id", "group_id", "run_id"
        ),
    )
    __mapper_args__ = {
        "polymorphic_on": "kind",
        "polymorphic_identity": "message",
    }

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.uuidv7()
    )

    # User and group identifiers
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Discriminator column for inheritance
    kind: Mapped[str] = mapped_column(String(20), nullable=False)

    # JSONB column for parts - stores serialized message parts
    parts: Mapped[list[dict[str, Any]]] = mapped_column(
        DateTimeAwareJSONB, nullable=False, default=list
    )

    # Timestamp of the message
    timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Unique identifier of the agent run
    run_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # JSONB column for metadata with alias 'meta' to avoid PostgreSQL reserved word
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, default=None
    )


class ModelRequest(ModelMessage):
    """
    SQLAlchemy ORM model for ModelRequest.

    Uses joined table inheritance - parent table + child table with request-specific fields.
    """

    __tablename__ = "model_requests"
    __mapper_args__ = {
        "polymorphic_identity": "request",
        "polymorphic_load": "selectin",
    }

    # Foreign key to parent table
    id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("model_messages.id"), primary_key=True
    )

    # Instructions for the model
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ModelResponse(ModelMessage):
    """
    SQLAlchemy ORM model for ModelResponse.

    Uses joined table inheritance - parent table + child table with response-specific fields.
    """

    __tablename__ = "model_responses"
    __mapper_args__ = {
        "polymorphic_identity": "response",
        "polymorphic_load": "selectin",
    }

    # Foreign key to parent table
    id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("model_messages.id"), primary_key=True
    )

    # JSONB column for usage information
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Model name
    model_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Provider information
    provider_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    provider_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    provider_response_id: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )

    # JSONB column for provider_details
    provider_details: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, default=None
    )

    # Finish reason
    finish_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


__all__ = [
    "Base",
    "Message",
    "ModelMessage",
    "ModelRequest",
    "ModelResponse",
]
