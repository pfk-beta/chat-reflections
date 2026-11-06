"""Claude Code session transcripts (~/.claude/projects/<project>/<session>.jsonl).

Synced into data/raw/claude_code/<hostname>/ by `make sync-claude-code`.
Events form a tree via parentUuid (logicalParentUuid across compaction); we keep the branch
ending at the last message. One assistant turn (everything between two human prompts) becomes
one Message: searchable `content` = its text blocks, ordered `parts` = text/thinking/tool calls.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from chat_reflections.importers._io import parse_iso
from chat_reflections.models import Conversation, Message

GLOBS = ["**/*.jsonl"]
MAX_OUTPUT = 20_000


def _blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    content = event["message"]["content"]
    return [{"type": "text", "text": content}] if isinstance(content, str) else content


def _tool_output(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, list):
        content = "\n".join(c.get("text", f"[{c.get('type')}]") for c in content)
    text = content or ""
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n… (truncated, {len(text)} chars total)"
    return text


def _current_branch(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_uuid = {e["uuid"]: e for e in events if "uuid" in e}
    msgs = [e for e in events if e.get("type") in ("user", "assistant")]
    path, cur = [], msgs[-1] if msgs else None
    while cur:
        if cur.get("type") in ("user", "assistant"):
            path.append(cur)
        parent = cur.get("parentUuid") or cur.get("logicalParentUuid")
        cur = by_uuid.get(parent) if parent else None
    return path[::-1]


def _tag(text: str, name: str) -> str | None:
    m = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
    return m.group(1).strip() if m else None


def _command(text: str) -> dict[str, Any] | None:
    """Slash command (`/clear`) or `!` shell command typed by the user, as a collapsed part."""
    if (name := _tag(text, "command-name")) is not None:
        return {"type": "command", "name": name, "args": _tag(text, "command-args") or ""}
    if (cmd := _tag(text, "bash-input")) is not None:
        return {"type": "command", "name": "!", "args": cmd}
    return None


def _command_output(text: str) -> str | None:
    outs = [_tag(text, t) for t in ("local-command-stdout", "bash-stdout", "bash-stderr")]
    if all(o is None for o in outs):
        return None
    return "\n".join(o for o in outs if o)


def _is_prompt(event: dict[str, Any]) -> bool:
    return event["type"] == "user" and not any(b["type"] == "tool_result" for b in _blocks(event))


def _build_messages(path: list[dict[str, Any]], results: dict[str, dict]) -> list[Message]:
    messages: list[Message] = []
    turn: Message | None = None
    for e in path:
        if e.get("isMeta") or (e["type"] == "user" and not _is_prompt(e)):
            continue
        ts = parse_iso(e["timestamp"])
        if e["type"] == "user":
            turn = None
            text = "\n".join(b["text"] for b in _blocks(e) if b["type"] == "text")
            if not text.strip():
                continue
            cmd, output = _command(text), _command_output(text)
            if cmd is None and output is not None:
                # output arrives as a separate event right after its command
                last = messages[-1].parts[-1] if messages and messages[-1].parts else {}
                if last.get("type") == "command" and "output" not in last:
                    last["output"] = output
                    continue
                cmd = {"type": "command", "name": "", "args": ""}
            if cmd is not None:
                if output is not None:
                    cmd["output"] = output
                content = f"{cmd['name']} {cmd['args']}".strip()
                messages.append(Message(e["uuid"], "user", content, ts, raw=e, parts=[cmd]))
                continue
            parts = [{"type": "summary", "text": text}] if e.get("isCompactSummary") else []
            messages.append(
                Message(e["uuid"], "user", "" if parts else text, ts, raw=e, parts=parts)
            )
            continue
        if turn is None:
            turn = Message(e["uuid"], "assistant", "", ts, e["message"].get("model"), raw={})
            turn.raw["events"] = []
            messages.append(turn)
        turn.raw["events"].append(e)
        for b in _blocks(e):
            if b["type"] == "text" and b["text"].strip():
                turn.parts.append({"type": "text", "text": b["text"]})
            elif b["type"] == "thinking" and b.get("thinking", "").strip():
                turn.parts.append({"type": "thinking", "text": b["thinking"]})
            elif b["type"] == "tool_use":
                result = results.get(b["id"], {})
                turn.parts.append(
                    {
                        "type": "tool",
                        "name": b["name"],
                        "input": b.get("input", {}),
                        "output": _tool_output(result) if result else None,
                        "is_error": bool(result.get("is_error")),
                    }
                )
    for m in messages:
        if m.role == "assistant":
            m.content = "\n\n".join(p["text"] for p in m.parts if p["type"] == "text")
    return [m for m in messages if m.content or m.parts]


def parse(path: Path) -> Iterator[Conversation]:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    results = {
        b["tool_use_id"]: b
        for e in events
        if e.get("type") == "user"
        for b in _blocks(e)
        if b["type"] == "tool_result"
    }
    messages = _build_messages(_current_branch(events), results)
    if not messages:
        return
    stamps = sorted(parse_iso(e["timestamp"]) for e in events if e.get("timestamp"))
    titles = [e["aiTitle"] for e in events if e.get("type") == "ai-title"]
    titles += [e["summary"] for e in events if e.get("type") == "summary"]
    first_prompt = next((m.content for m in messages if m.role == "user" and m.content), "")
    title = titles[-1] if titles else first_prompt[:100] or "(untitled)"
    session_id = next(e["sessionId"] for e in events if e.get("sessionId"))
    is_subagent = path.parent.name == "subagents"
    if is_subagent:
        title = f"[subagent] {first_prompt[:100]}"
    yield Conversation(
        source="claude_code",
        external_id=f"{session_id}-{path.stem}" if is_subagent else session_id,
        title=title,
        created_at=stamps[0],
        updated_at=stamps[-1],
        messages=messages,
        project=next((e["cwd"] for e in events if e.get("cwd")), None),
        raw={"session_id": session_id, "file": path.name},
    )
