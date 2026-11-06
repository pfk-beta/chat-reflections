import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from chat_reflections import es, markdown
from chat_reflections.importers import IMPORTERS

app = FastAPI(title="chat-reflections")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
client = es.client()

templates.env.filters["md"] = markdown.render
templates.env.filters["home"] = lambda p: p.replace(str(Path.home()), "~", 1) if p else p

PAGE_SIZE = 50
ALL = "all"
DOC_INDICES = {"conversations": es.CONVERSATIONS, "messages": es.MESSAGES}
LABELS = {ALL: "All", "openwebui": "Open WebUI", "claude_code": "Claude Code", "chatgpt": "ChatGPT"}
templates.env.filters["label"] = lambda s: LABELS.get(s, s.capitalize())


def _source(source: str) -> str | None:
    if source != ALL and source not in IMPORTERS:
        raise HTTPException(404)
    return None if source == ALL else source


@app.get("/api/search")
def api_search(q: str, source: str | None = None, size: int = 20) -> list[dict[str, Any]]:
    return es.search(client, q, source, size)


@app.get("/api/conversations/{conversation_id}")
def api_conversation(conversation_id: str) -> dict[str, Any]:
    conv = es.get_conversation(client, conversation_id)
    if conv is None:
        raise HTTPException(404)
    return conv


@app.get("/api/docs/{kind}/{doc_id:path}")
def api_doc(kind: str, doc_id: str) -> dict[str, Any]:
    """Stored ES document, including the original export fragment under `raw`."""
    if kind not in DOC_INDICES:
        raise HTTPException(404)
    doc = es.get_doc(client, DOC_INDICES[kind], doc_id)
    if doc is None:
        raise HTTPException(404)
    return doc


_MAGIC = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}


def _image_type(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return next(
        (t for sig, t in _MAGIC.items() if data.startswith(sig)), "application/octet-stream"
    )


@app.get("/api/images/{n}/{message_id:path}")
def api_image(n: int, message_id: str) -> Response:
    """n-th part of a message, which must be an image part; read from the export zip on demand.
    The archive path comes from the index, never from the request."""
    doc = es.get_doc(client, es.MESSAGES, message_id)
    parts = (doc or {}).get("parts") or []
    if not 0 <= n < len(parts) or parts[n].get("type") != "image":
        raise HTTPException(404)
    try:
        with zipfile.ZipFile(parts[n]["archive"]) as zf:
            data = zf.read(parts[n]["member"])
    except (OSError, KeyError) as e:
        raise HTTPException(404, "image file not found in data/raw") from e
    return Response(data, media_type=_image_type(data), headers={"Cache-Control": "max-age=86400"})


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    counts = es.source_counts(client)
    cards = [(ALL, sum(counts.values()))] + [(s, counts.get(s, 0)) for s in IMPORTERS]
    return templates.TemplateResponse(request, "index.html", {"cards": cards})


@app.get("/browse/{source}", response_class=HTMLResponse)
def browse(
    request: Request, source: str, page: int = 1, c: str = "", project: str = ""
) -> HTMLResponse:
    page = max(page, 1)
    src = _source(source)
    items, total = es.recent(client, src, page, PAGE_SIZE, project or None)
    conv = es.get_conversation(client, c) if c else None
    return templates.TemplateResponse(
        request,
        "browse.html",
        {
            "source": source,
            "project": project,
            "projects": es.projects(client, src),
            "items": items,
            "page": page,
            "pages": -(-total // PAGE_SIZE),
            "total": total,
            "conv": conv,
        },
    )


@app.get("/search/{source}", response_class=HTMLResponse)
def search(
    request: Request, source: str, q: str = "", c: str = "", project: str = ""
) -> HTMLResponse:
    src = _source(source)
    results = es.search(client, q, src, 50, project or None) if q else []
    conv = es.get_conversation(client, c) if c else None
    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "source": source,
            "q": q,
            "project": project,
            "projects": es.projects(client, src),
            "results": results,
            "conv": conv,
        },
    )
