"""Gemini via Google Takeout → "My Activity" → Gemini Apps (JSON format). The export is a flat
list of prompts (`title`, localized prefix) with the answer as HTML (`safeHtmlItem`); entries
are grouped into conversations by the `gemini.google.com/app/<id>` link in `details`."""

import json
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from fnmatch import fnmatch
from html.parser import HTMLParser
from pathlib import Path

from chat_reflections.importers._io import image_part, parse_iso
from chat_reflections.models import Conversation, Message

GLOBS = ["*.zip", "*.json"]
MEMBER = "*Gemini*/*.json"
_PROMPT_PREFIX = re.compile(r"^(?:Prompted|Wysłano zapytanie:)\s*")
_APP_URL = re.compile(r"gemini\.google\.com/app/(\w+)")


class _Markdown(HTMLParser):
    """Just enough HTML → Markdown for Gemini answers (p, headings, lists, code, links)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.lists: list[str] = []
        self.pre = False
        self.href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code" and not self.pre:
            self.out.append("`")
        elif tag == "pre":
            self.pre = True
            self.out.append("\n\n```\n")
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("ul", "ol"):
            self.lists.append(tag)
        elif tag == "li":
            bullet = "1. " if self.lists and self.lists[-1] == "ol" else "- "
            self.out.append("\n" + "  " * (len(self.lists) - 1) + bullet)
        elif tag == "a":
            self.href = dict(attrs).get("href")
            self.out.append("[")
        elif tag == "hr":
            self.out.append("\n\n---\n\n")
        elif tag == "br":
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code" and not self.pre:
            self.out.append("`")
        elif tag == "pre":
            self.pre = False
            self.out.append("```\n\n" if self.out[-1].endswith("\n") else "\n```\n\n")
        elif tag == "p" or re.fullmatch(r"h[1-6]", tag):
            self.out.append(" " if self.lists else "\n\n")
        elif tag in ("ul", "ol"):
            self.lists.pop()
            if not self.lists:
                self.out.append("\n\n")
        elif tag == "a":
            self.out.append(f"]({self.href})" if self.href else "]")

    def handle_data(self, data: str) -> None:
        if self.pre:
            self.out.append(data)
        elif data.strip():
            self.out.append(re.sub(r"\s+", " ", data))


def html_to_markdown(html: str) -> str:
    p = _Markdown()
    p.feed(html)
    p.close()
    text = re.sub(r"[ \t]+\n", "\n", "".join(p.out))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _load(path: Path) -> tuple[list[dict], dict[str, str]]:
    """Activity entries and image members of the Gemini folder, keyed by file name and by stem
    (Takeout sometimes converts images, so `x.png` in the JSON is `x.jpg` in the zip)."""
    if path.suffix != ".zip":
        return json.loads(path.read_text(encoding="utf-8")), {}
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if fnmatch(n, "*Gemini*/*")]
        entries = [e for n in names if fnmatch(n, MEMBER) for e in json.loads(zf.read(n))]
    files = {Path(n).stem: n for n in names} | {Path(n).name: n for n in names}
    return entries, files


def _images(path: Path, files: dict[str, str], names: list[str]) -> list[dict]:
    members = [files.get(n) or files.get(Path(n).stem) for n in names]
    return [image_part(path, m, Path(m).name) for m in members if m]


def parse(path: Path) -> Iterator[Conversation]:
    entries, files = _load(path)
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        if "title" not in e or "time" not in e:
            continue
        urls = [
            m.group(1) for d in e.get("details", []) if (m := _APP_URL.search(d.get("url", "")))
        ]
        groups[urls[0] if urls else e["time"]].append(e)

    for conv_id, entries in groups.items():
        entries.sort(key=lambda e: e["time"])
        messages: list[Message] = []
        for e in entries:
            ts = parse_iso(e["time"])
            prompt = _PROMPT_PREFIX.sub("", e["title"])
            # imageFile = the user's upload; other attachedFiles = images Gemini generated
            uploaded = [e["imageFile"]] if e.get("imageFile") else []
            generated = [f for f in e.get("attachedFiles", []) if f not in uploaded]
            images = _images(path, files, uploaded)
            if prompt.strip() or images:
                text = [{"type": "text", "text": prompt}] if prompt.strip() else []
                parts = [*text, *images] if images else []
                messages.append(
                    Message(f"{e['time']}:prompt", "user", prompt, ts, raw=e, parts=parts)
                )
            answer = "\n\n".join(html_to_markdown(h["html"]) for h in e.get("safeHtmlItem", []))
            images = _images(path, files, generated)
            if answer.strip() or images:
                text = [{"type": "text", "text": answer}] if answer.strip() else []
                parts = [*text, *images] if images else []
                messages.append(
                    Message(f"{e['time']}:response", "assistant", answer, ts, parts=parts)
                )
        if not messages:
            continue
        first = messages[0].content
        yield Conversation(
            source="gemini",
            external_id=conv_id,
            title=first if len(first) <= 80 else first[:79] + "…",
            created_at=parse_iso(entries[0]["time"]),
            updated_at=parse_iso(entries[-1]["time"]),
            messages=messages,
        )
