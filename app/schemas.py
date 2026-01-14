from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Sequence, TypeAlias, Union
from uuid import UUID
from zoneinfo import ZoneInfo

from arcanus.base import BaseTransmuter, Identity
from arcanus.materia.sqlalchemy import SqlalchemyMateria
from pydantic import ConfigDict, Discriminator, Field, Tag, TypeAdapter
from pydantic_ai import UserPromptPart
from pydantic_ai.messages import (
    FinishReason,
    ModelRequestPart,
    ModelResponsePart,
)
from pydantic_ai.usage import RequestUsage

from app import models

# Initialize SQLAlchemy Materia for blessing
sqlalchemy_materia = SqlalchemyMateria()

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _now_shanghai() -> datetime:
    return datetime.now(SHANGHAI_TZ)


@sqlalchemy_materia.bless(models.Message)
class Message(BaseTransmuter):
    """Transmuter for Message - binds to SQLAlchemy ORM."""

    id: Annotated[Optional[UUID], Identity] = Field(default=None, frozen=True)
    user_id: int
    group_id: Optional[int] = None
    kind: Literal["request", "response"]
    content: str
    timestamp: datetime = Field(default_factory=_now_shanghai)


@sqlalchemy_materia.bless(models.ModelRequest)
class ModelRequest(BaseTransmuter):
    """Transmuter for ModelRequest - detailed request tracking.

    Duck-typed to be compatible with pydantic_ai.messages.ModelRequest.
    """

    model_config = ConfigDict(
        from_attributes=True,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )

    # ORM-specific field (not in pydantic_ai original)
    id: Annotated[Optional[UUID], Identity] = Field(
        default=None, frozen=True, exclude=True
    )
    user_id: int = Field(frozen=True, exclude=True)
    group_id: Optional[int] = Field(default=None, frozen=True, exclude=True)

    # pydantic_ai.messages.ModelRequest compatible fields
    parts: Sequence[ModelRequestPart] = Field(default_factory=list)
    timestamp: Optional[datetime] = None
    instructions: Optional[str] = None
    kind: Literal["request"] = "request"
    run_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = Field(default=None, alias="meta")

    @classmethod
    def user_text_prompt(
        cls,
        user_id: int,
        user_prompt: str,
        *,
        group_id: int | None = None,
        instructions: str | None = None,
    ) -> ModelRequest:
        """Create a `ModelRequest` with a single user prompt as text."""
        return cls(
            user_id=user_id,
            group_id=group_id,
            parts=[UserPromptPart(user_prompt)],
            instructions=instructions,
        )


@sqlalchemy_materia.bless(models.ModelResponse)
class ModelResponse(BaseTransmuter):
    """Transmuter for ModelResponse - detailed response tracking.

    Duck-typed to be compatible with pydantic_ai.messages.ModelResponse.
    """

    model_config = ConfigDict(
        from_attributes=True,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )

    # ORM-specific field (not in pydantic_ai original)
    id: Annotated[Optional[UUID], Identity] = Field(
        default=None, frozen=True, exclude=True
    )
    user_id: Optional[int] = Field(default=None, frozen=True, exclude=True)
    group_id: Optional[int] = Field(default=None, frozen=True, exclude=True)

    # pydantic_ai.messages.ModelResponse compatible fields
    parts: Sequence[ModelResponsePart] = Field(default_factory=list)
    usage: RequestUsage = Field(default_factory=RequestUsage)
    model_name: Optional[str] = None
    timestamp: datetime = Field(default_factory=_now_shanghai)
    kind: Literal["response"] = "response"
    provider_name: Optional[str] = None
    provider_url: Optional[str] = None
    provider_details: Optional[dict[str, Any]] = None
    provider_response_id: Optional[str] = None
    finish_reason: Optional[FinishReason] = None
    run_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = Field(default=None, alias="meta")


# Smart discriminated union for ModelMessage
ModelMessage: TypeAlias = Annotated[
    Union[
        Annotated[ModelRequest, Tag("request")],
        Annotated[ModelResponse, Tag("response")],
    ],
    Discriminator("kind"),
]
ModelMessagesTypeAdapter = TypeAdapter(
    list[ModelMessage],
    config=ConfigDict(
        defer_build=True,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    ),
)


sqlalchemy_materia.bless(models.ModelMessage)(ModelMessage)  # pyright: ignore[reportArgumentType]


__all__ = [
    "sqlalchemy_materia",
    "Message",
    "ModelRequest",
    "ModelResponse",
    "ModelMessage",
]
