"""ChatGPT export (Settings → Data controls → Export). Conversations live in
`conversations.json` or sharded `conversations-NNN.json`; each is a tree in `mapping`
(edits/regenerations), we follow `current_node` up to the root. Consecutive assistant nodes
(reasoning `thoughts` + answer) are merged into one Message with parts."""

import json
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from chat_reflections.importers._io import from_epoch, image_part, load_json_all, parse_iso
from chat_reflections.models import Conversation, Message

GLOBS = ["*.zip", "conversations*.json"]

# Private-use markers in answers: kindpayload (citations, entities, image
# groups) and … /  around cited spans.
_ENTITY = re.compile("(?:entity|product_entity|product)(.*?)", re.S)
_MARKER = re.compile("[^]*|[]")


def _entity_name(m: re.Match) -> str:
    try:
        value = json.loads(m.group(1))
    except json.JSONDecodeError:
        return ""
    return str(value[1]) if isinstance(value, list) and len(value) > 1 else ""


def _clean(text: str) -> str:
    return _MARKER.sub("", _ENTITY.sub(_entity_name, text))


def _current_branch(c: dict) -> list[dict]:
    path, cur = [], c.get("current_node")
    while cur:
        node = c["mapping"][cur]
        if node.get("message"):
            path.append(node["message"])
        cur = node.get("parent")
    return path[::-1]


@dataclass
class _Assets:
    """Image files in the export zip: `file-…`/`file_….dat` members, their original names
    (`conversation_asset_file_names.json`) and generated images (`library_files.json`, linked to
    a conversation only by `origination_thread_id`; the image-gen messages are not exported)."""

    archive: Path
    members: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    generated: dict[str, list[dict]] = field(default_factory=dict)

    def part(self, file_id: str, name: str = "") -> dict | None:
        member = self.members.get(file_id)
        if member is None:
            return None
        return image_part(self.archive, member, name or self.names.get(member.rsplit("/")[-1], ""))


def _load_assets(path: Path) -> _Assets:
    assets = _Assets(path)
    if path.suffix != ".zip":
        return assets
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        for n in names:
            if m := re.match(r"(file[-_][A-Za-z0-9]+)", n.rsplit("/")[-1]):
                assets.members[m.group(1)] = n
        if "conversation_asset_file_names.json" in names:
            assets.names = json.loads(zf.read("conversation_asset_file_names.json"))
        if "library_files.json" in names:
            for f in json.loads(zf.read("library_files.json")):
                if f.get("origination_thread_id") and f.get("file_id"):
                    assets.generated.setdefault(f["origination_thread_id"], []).append(f)
    return assets


def _content(content: dict, assets: _Assets) -> tuple[str, list[dict]]:
    """Searchable text and ordered parts (text + images) of a message."""
    texts, parts = [], []
    for p in content.get("parts") or []:
        if isinstance(p, str) and (text := _clean(p)).strip():
            texts.append(text)
            parts.append({"type": "text", "text": text})
        elif isinstance(p, dict) and p.get("content_type") == "image_asset_pointer":
            file_id = p.get("asset_pointer", "").rsplit("/")[-1]
            if image := assets.part(file_id):
                parts.append(image)
            else:
                texts.append("[image]")
                parts.append({"type": "text", "text": "[image]"})
    return "\n\n".join(texts), parts


def _has_image(m: Message) -> bool:
    return any(p["type"] == "image" for p in m.parts)


def _add_generated(messages: list[Message], images: list[dict], assets: _Assets) -> None:
    """Attach each generated image to the assistant turn it was made in (by time), or insert an
    assistant message when the export lost that turn entirely."""
    for f in sorted(images, key=lambda f: f.get("created_at", "")):
        part = assets.part(f["file_id"], f.get("file_name", ""))
        if part is None:
            continue
        ts = parse_iso(f["created_at"]) if f.get("created_at") else None
        i = len(messages)
        if ts:
            i = next((k for k, m in enumerate(messages) if m.created_at and m.created_at > ts), i)
        prev = messages[i - 1] if i else None
        if prev and prev.role == "assistant":
            prev.parts.append(part)
        else:
            text = Path(f.get("file_name", "")).stem
            messages.insert(i, Message(f["file_id"], "assistant", text, ts, raw=f, parts=[part]))


def _build_messages(nodes: list[dict], assets: _Assets) -> list[Message]:
    messages: list[Message] = []
    for m in nodes:
        role, content = m["author"]["role"], m["content"]
        ts = from_epoch(m["create_time"]) if m.get("create_time") else None
        model = (m.get("metadata") or {}).get("model_slug")
        if role == "user":
            text, parts = _content(content, assets)
            msg = Message(m["id"], "user", text, ts, raw=m, parts=parts)
            if not _has_image(msg):
                msg.parts = []
            if text.strip() or msg.parts:
                messages.append(msg)
            continue
        if role != "assistant":
            continue
        if content["content_type"] == "thoughts":
            thinking = "\n\n".join(
                t.get("content") or t.get("summary") or "" for t in content.get("thoughts", [])
            )
            parts = [{"type": "thinking", "text": thinking}] if thinking.strip() else []
            text = ""
        elif content["content_type"] in ("text", "multimodal_text"):
            text, parts = _content(content, assets)
        else:  # reasoning_recap ("Thought for 12s"), tool/code payloads
            continue
        if not parts:
            continue
        prev = messages[-1] if messages else None
        if prev and prev.role == "assistant":
            prev.parts += parts
            prev.content = "\n\n".join(s for s in (prev.content, text) if s)
            prev.model = prev.model or model
        else:
            messages.append(Message(m["id"], "assistant", text, ts, model, raw=m, parts=parts))
    return [m for m in messages if m.content.strip() or _has_image(m)]


def parse(path: Path) -> Iterator[Conversation]:
    assets = _load_assets(path)
    for shard in load_json_all(path, "conversations*.json"):
        for c in shard:
            created = from_epoch(c["create_time"])
            conv_id = c.get("conversation_id") or c["id"]
            messages = _build_messages(_current_branch(c), assets)
            _add_generated(messages, assets.generated.get(conv_id, []), assets)
            yield Conversation(
                source="chatgpt",
                external_id=conv_id,
                title=c.get("title") or "(untitled)",
                created_at=created,
                updated_at=from_epoch(c["update_time"]) if c.get("update_time") else created,
                messages=messages,
                raw={k: v for k, v in c.items() if k != "mapping"},
            )
