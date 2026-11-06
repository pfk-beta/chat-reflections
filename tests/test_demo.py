from pathlib import Path

from chat_reflections.cli import iter_source
from chat_reflections.importers import IMPORTERS

DEMO = Path(__file__).parent.parent / "demo/raw"


def test_demo_data_covers_every_source() -> None:
    counts = {s: len(iter_source(s, DEMO)) for s in IMPORTERS}
    assert all(counts.values()), counts


def test_demo_openwebui_follows_regenerated_branch() -> None:
    [c] = iter_source("openwebui", DEMO)
    assert len(c.messages) == 4
    assert "I keep both" in c.messages[1].content
