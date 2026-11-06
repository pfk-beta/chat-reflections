from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Message:
    external_id: str
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime | None = None
    model: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    # ordered blocks for rich rendering (text/thinking/tool/summary); content stays the search text
    parts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Conversation:
    source: str
    external_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[Message] = field(default_factory=list)
    project: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.source}:{self.external_id}"
