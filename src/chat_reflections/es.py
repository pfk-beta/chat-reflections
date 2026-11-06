import os
from collections.abc import Iterable
from typing import Any

from elasticsearch import Elasticsearch, helpers

from chat_reflections.models import Conversation

ES_URL = os.environ.get("ES_URL", "http://localhost:9200")
PREFIX = os.environ.get("ES_PREFIX", "chat")
CONVERSATIONS = f"{PREFIX}-conversations"
MESSAGES = f"{PREFIX}-messages"

BUILTIN_LANGUAGES = {
    "arabic", "armenian", "basque", "bengali", "brazilian", "bulgarian", "catalan", "cjk",
    "czech", "danish", "dutch", "english", "estonian", "finnish", "french", "galician",
    "german", "greek", "hindi", "hungarian", "indonesian", "irish", "italian", "latvian",
    "lithuanian", "norwegian", "persian", "portuguese", "romanian", "russian", "sorani",
    "spanish", "swedish", "thai", "turkish",
}  # fmt: skip
# languages served by plugins installed in docker/Dockerfile.es -> analyzer name
PLUGIN_LANGUAGES = {
    "polish": "polish",
    "ukrainian": "ukrainian",
    "japanese": "kuromoji",
    "chinese": "smartcn",
    "korean": "nori",
}


def analyzer_for(language: str) -> str:
    if language in PLUGIN_LANGUAGES:
        return PLUGIN_LANGUAGES[language]
    if language in BUILTIN_LANGUAGES:
        return language
    supported = ", ".join(sorted(BUILTIN_LANGUAGES | PLUGIN_LANGUAGES.keys()))
    raise ValueError(f"Unsupported language {language!r} in CHAT_LANGUAGES. Supported: {supported}")


LANGUAGES = [
    lang.strip().lower()
    for lang in os.environ.get("CHAT_LANGUAGES", "english").split(",")
    if lang.strip()
]

# Base field: icu (no stemming; tokenization + diacritics folding for any language).
# One stemmed subfield per configured language; queries hit all of them.
_TEXT = {
    "type": "text",
    "analyzer": "icu_analyzer",
    "fields": {lang: {"type": "text", "analyzer": analyzer_for(lang)} for lang in LANGUAGES},
}


def _fields(name: str, boost: str = "") -> list[str]:
    return [f"{name}{boost}"] + [f"{name}.{lang}{boost}" for lang in LANGUAGES]


MAPPINGS: dict[str, dict[str, Any]] = {
    CONVERSATIONS: {
        "properties": {
            "source": {"type": "keyword"},
            "title": _TEXT,
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "message_count": {"type": "integer"},
            "models": {"type": "keyword"},
            "project": {"type": "keyword"},
            "raw": {"type": "object", "enabled": False},
        }
    },
    MESSAGES: {
        "properties": {
            "conversation_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "title": _TEXT,
            "position": {"type": "integer"},
            "role": {"type": "keyword"},
            "content": _TEXT,
            "created_at": {"type": "date"},
            "model": {"type": "keyword"},
            "project": {"type": "keyword"},
            "raw": {"type": "object", "enabled": False},
            "parts": {"type": "object", "enabled": False},
        }
    },
}


def client() -> Elasticsearch:
    return Elasticsearch(ES_URL)


def recreate_indices(es: Elasticsearch) -> None:
    for name, mapping in MAPPINGS.items():
        es.indices.delete(index=name, ignore_unavailable=True)
        es.indices.create(index=name, mappings=mapping)


def _actions(conversations: Iterable[Conversation]) -> Iterable[dict[str, Any]]:
    for c in conversations:
        yield {
            "_index": CONVERSATIONS,
            "_id": c.id,
            "source": c.source,
            "title": c.title,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "message_count": len(c.messages),
            "models": sorted({m.model for m in c.messages if m.model}),
            "project": c.project,
            "raw": c.raw,
        }
        for i, m in enumerate(c.messages):
            yield {
                "_index": MESSAGES,
                "_id": f"{c.id}:{m.external_id}",
                "conversation_id": c.id,
                "source": c.source,
                "title": c.title,
                "position": i,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
                "model": m.model,
                "project": c.project,
                "raw": m.raw,
                "parts": m.parts,
            }


def index(es: Elasticsearch, conversations: Iterable[Conversation]) -> int:
    ok, _ = helpers.bulk(es, _actions(conversations), refresh=True)
    return ok


def _filters(source: str | None, project: str | None) -> list[dict[str, Any]]:
    return [{"term": {k: v}} for k, v in (("source", source), ("project", project)) if v]


def search(
    es: Elasticsearch,
    q: str,
    source: str | None = None,
    size: int = 20,
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Full-text search over messages, one hit (best message) per conversation."""
    filters = _filters(source, project)
    resp = es.search(
        index=MESSAGES,
        size=size,
        query={
            "bool": {
                "must": {
                    "multi_match": {
                        "query": q,
                        "fields": _fields("content") + _fields("title", "^2"),
                    }
                },
                "filter": filters,
            }
        },
        collapse={"field": "conversation_id"},
        highlight={
            "fields": {
                f: {"fragment_size": 200, "number_of_fragments": 2} for f in _fields("content")
            },
            "encoder": "html",
            "pre_tags": ["<mark>"],
            "post_tags": ["</mark>"],
        },
        source_excludes=["content", "raw", "parts"],
    )
    return [{**h["_source"], "highlight": _best_highlight(h)} for h in resp["hits"]["hits"]]


def _best_highlight(hit: dict[str, Any]) -> list[str]:
    """Stemmed matches only highlight in their language subfield; prefer the richest one."""
    fragments = hit.get("highlight", {}).values()
    return max(fragments, key=lambda f: sum(s.count("<mark>") for s in f), default=[])


def recent(
    es: Elasticsearch,
    source: str | None = None,
    page: int = 1,
    size: int = 50,
    project: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    query = {"bool": {"filter": _filters(source, project)}}
    resp = es.search(
        index=CONVERSATIONS,
        from_=(page - 1) * size,
        size=size,
        query=query,
        sort=[{"updated_at": "desc"}],
        source_excludes=["raw"],
    )
    items = [{"id": h["_id"], **h["_source"]} for h in resp["hits"]["hits"]]
    return items, resp["hits"]["total"]["value"]


def get_conversation(es: Elasticsearch, conversation_id: str) -> dict[str, Any] | None:
    conv = es.options(ignore_status=404).get(
        index=CONVERSATIONS, id=conversation_id, source_excludes=["raw"]
    )
    if not conv.get("found"):
        return None
    msgs = es.search(
        index=MESSAGES,
        size=10_000,
        query={"term": {"conversation_id": conversation_id}},
        sort=[{"position": "asc"}],
        source_excludes=["raw"],
    )
    return {
        "id": conversation_id,
        **conv["_source"],
        "messages": [{"id": h["_id"], **h["_source"]} for h in msgs["hits"]["hits"]],
    }


def get_doc(es: Elasticsearch, index: str, doc_id: str) -> dict[str, Any] | None:
    doc = es.options(ignore_status=404).get(index=index, id=doc_id)
    return doc["_source"] if doc.get("found") else None


def source_counts(es: Elasticsearch) -> dict[str, int]:
    resp = es.search(index=CONVERSATIONS, size=0, aggs={"s": {"terms": {"field": "source"}}})
    return {b["key"]: b["doc_count"] for b in resp["aggregations"]["s"]["buckets"]}


def projects(es: Elasticsearch, source: str | None = None) -> list[str]:
    resp = es.search(
        index=CONVERSATIONS,
        size=0,
        query={"bool": {"filter": _filters(source, None)}},
        aggs={"p": {"terms": {"field": "project", "size": 500, "order": {"_key": "asc"}}}},
    )
    return [b["key"] for b in resp["aggregations"]["p"]["buckets"]]
