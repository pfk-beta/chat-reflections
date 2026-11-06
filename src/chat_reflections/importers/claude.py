from collections.abc import Iterator
from pathlib import Path

from chat_reflections.importers._io import load_json, parse_iso
from chat_reflections.models import Conversation, Message

GLOBS = ["*conversations*.zip", "conversations*.json"]
ROLES = {"human": "user", "assistant": "assistant"}


def parse(path: Path) -> Iterator[Conversation]:
    for c in load_json(path, "conversations.json"):
        messages = [
            Message(
                external_id=m["uuid"],
                role=ROLES[m["sender"]],
                content=m["text"],
                created_at=parse_iso(m["created_at"]),
                raw=m,
            )
            for m in c["chat_messages"]
            if m["text"].strip()
        ]
        yield Conversation(
            source="claude",
            external_id=c["uuid"],
            title=c["name"] or "(untitled)",
            created_at=parse_iso(c["created_at"]),
            updated_at=parse_iso(c["updated_at"]),
            messages=messages,
            raw={k: v for k, v in c.items() if k != "chat_messages"},
        )
