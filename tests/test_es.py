import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from chat_reflections import es
from chat_reflections.cli import iter_source
from chat_reflections.importers import IMPORTERS

assert es.PREFIX == "test-chat", "tests/conftest.py must set ES_PREFIX before es is imported"

pytestmark = pytest.mark.es
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def client() -> Iterator:
    c = es.client()
    if not c.ping():
        if os.environ.get("CI"):
            pytest.fail("Elasticsearch not running")
        pytest.skip("Elasticsearch not running")
    es.recreate_indices(c)
    for source in IMPORTERS:
        es.index(c, iter_source(source, FIX))
    yield c
    for name in es.MAPPINGS:
        c.indices.delete(index=name)


def test_polish_stemming(client) -> None:
    hits = es.search(client, "rysunek")
    assert [h["conversation_id"] for h in hits] == ["openwebui:o1"]
    assert "<mark>rysunkami</mark>" in hits[0]["highlight"][0]


def test_english_stemming(client) -> None:
    hits = es.search(client, "emulator")
    assert [h["conversation_id"] for h in hits] == ["claude:c1"]


def test_icu_folds_diacritics(client) -> None:
    hits = es.search(client, "zrob album")
    assert hits[0]["conversation_id"] == "openwebui:o1"


def test_get_conversation(client) -> None:
    conv = es.get_conversation(client, "claude:c1")
    assert conv is not None
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]


def test_recent_pagination(client) -> None:
    page1, total = es.recent(client, page=1, size=3)
    page2, _ = es.recent(client, page=2, size=3)
    assert total == 10
    assert len(page1) == 3 and len(page2) == 3
    assert not {c["id"] for c in page1} & {c["id"] for c in page2}


def test_project_filter(client) -> None:
    assert es.projects(client, "claude_code") == ["/home/x/proj"]
    assert es.projects(client, "claude") == []
    items, total = es.recent(client, "claude_code", project="/home/x/proj")
    assert total == 3
    assert es.search(client, "ruff", project="/home/x/proj")[0]["conversation_id"] == (
        "claude_code:s1"
    )
    assert es.search(client, "ruff", project="/other") == []


def test_raw_not_in_conversation_but_in_doc(client) -> None:
    conv = es.get_conversation(client, "claude:c1")
    assert conv is not None
    assert "raw" not in conv and "raw" not in conv["messages"][0]
    doc = es.get_doc(client, es.MESSAGES, conv["messages"][0]["id"])
    assert doc is not None and doc["raw"]["uuid"] == "m1"


def test_web_pages(client) -> None:
    from fastapi.testclient import TestClient

    from chat_reflections.web import app

    web = TestClient(app)
    for url in [
        "/",
        "/browse/all",
        "/browse/claude?c=claude%3Ac1",
        "/search/perplexity?q=obiad",
        "/search/all?q=firebase&c=claude%3Ac1",
        "/api/docs/messages/claude%3Ac1%3Am1",
    ]:
        assert web.get(url).status_code == 200, url
    assert web.get("/browse/nope").status_code == 404
    assert "Uruchom firebase" in web.get("/browse/claude?c=claude:c1").text
    page = web.get("/browse/claude_code?project=%2Fhome%2Fx%2Fproj&c=claude_code%3As1").text
    assert "<b>Bash</b>" in page and "1 failed" in page and "💭 thinking" in page
