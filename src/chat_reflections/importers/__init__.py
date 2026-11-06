"""Each importer module exposes GLOBS (files it handles in data/raw/<source>/) and
parse(path) -> Iterator[Conversation]."""

from types import ModuleType

from chat_reflections.importers import chatgpt, claude, claude_code, gemini, openwebui, perplexity

IMPORTERS: dict[str, ModuleType] = {
    "chatgpt": chatgpt,
    "claude": claude,
    "gemini": gemini,
    "perplexity": perplexity,
    "openwebui": openwebui,
    "claude_code": claude_code,
}
