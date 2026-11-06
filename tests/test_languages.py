import pytest

from chat_reflections.es import analyzer_for


def test_analyzers() -> None:
    assert analyzer_for("english") == "english"
    assert analyzer_for("polish") == "polish"
    assert analyzer_for("japanese") == "kuromoji"


def test_unknown_language_fails_clearly() -> None:
    with pytest.raises(ValueError, match="Unsupported language 'klingon'.*english"):
        analyzer_for("klingon")
