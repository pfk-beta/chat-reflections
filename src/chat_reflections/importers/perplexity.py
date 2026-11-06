from collections.abc import Iterator
from pathlib import Path

from chat_reflections.importers._io import load_json, parse_iso
from chat_reflections.models import Conversation, Message

GLOBS = ["perplexity_*.zip", "conversations-*.json"]


def parse(path: Path) -> Iterator[Conversation]:
    for c in load_json(path, "conversations-*.json")["conversations"]:
        messages: list[Message] = []
        for e in c["entries"]:
            ts = parse_iso(e["created_at"])
            messages.append(Message(f"{e['entry_uuid']}:q", "user", e["query"], ts, raw=e))
            if e["answer"]:
                messages.append(
                    Message(
                        f"{e['entry_uuid']}:a", "assistant", e["answer"], ts, e["engine_mode"], e
                    )
                )
        yield Conversation(
            source="perplexity",
            external_id=c["context_uuid"],
            title=c["context_title"] or "(untitled)",
            created_at=parse_iso(c["created_at"]),
            updated_at=parse_iso(c["updated_at"]),
            messages=messages,
            raw={k: v for k, v in c.items() if k != "entries"},
        )
