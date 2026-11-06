from collections.abc import Iterator
from pathlib import Path

from chat_reflections.importers._io import from_epoch, load_json
from chat_reflections.models import Conversation, Message

GLOBS = ["*chat-export*.json"]


def _current_branch(history: dict) -> list[dict]:
    """Messages form a tree (regenerations/edits); follow currentId up to the root."""
    path, cur = [], history.get("currentId")
    while cur:
        m = history["messages"][cur]
        path.append(m)
        cur = m.get("parentId")
    return path[::-1]


def parse(path: Path) -> Iterator[Conversation]:
    for c in load_json(path, "*.json"):
        messages = [
            Message(
                external_id=m["id"],
                role=m["role"],
                content=m["content"],
                created_at=from_epoch(m["timestamp"]) if m.get("timestamp") else None,
                model=m.get("model"),
                raw=m,
            )
            for m in _current_branch(c["chat"]["history"])
            if m["content"].strip()
        ]
        yield Conversation(
            source="openwebui",
            external_id=c["id"],
            title=c["title"] or "(untitled)",
            created_at=from_epoch(c["created_at"]),
            updated_at=from_epoch(c["updated_at"]),
            messages=messages,
            raw={**c, "chat": {k: v for k, v in c["chat"].items() if k != "history"}},
        )
