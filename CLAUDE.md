# chat-reflections

Local, single-user aggregator of LLM chat exports (ChatGPT, Claude, Gemini, Perplexity, OpenWebUI,
Claude Code sessions).
Full-text search over Elasticsearch, browsed via a minimal FastAPI + Jinja frontend. No auth.

## Architecture
- **Source of truth = export files in `data/raw/<source>/`** (gitignored, private). ES is a derived
  index; `make reindex` drops and rebuilds it from scratch. No database.
- `src/chat_reflections/models.py` — normalized `Conversation` / `Message` dataclasses.
- `src/chat_reflections/importers/<source>.py` — each exposes `GLOBS` (file patterns in
  `data/raw/<source>/`) and `parse(path) -> Iterator[Conversation]`. Registered in
  `importers/__init__.py`. Importers read `.zip` exports directly (`_io.load_json`).
- `src/chat_reflections/es.py` — index mappings, bulk indexing, search. Two indices:
  `{prefix}-conversations` (one doc per conversation) and `{prefix}-messages` (one doc per
  message, denormalized `title`/`source`; search collapses by `conversation_id`).
- Text fields: base field uses `icu_analyzer` (no stemming, diacritics folding) plus one stemmed
  subfield per language in `CHAT_LANGUAGES` (env / `.env`, default `english`), e.g.
  `content.polish`. Queries and highlights cover all subfields. Language → analyzer map in
  `es.py` (`BUILTIN_LANGUAGES`, `PLUGIN_LANGUAGES`); plugins installed in `docker/Dockerfile.es`.
  Changing languages requires a reindex. Tests pin `CHAT_LANGUAGES=polish,english`.
- Each `Conversation`/`Message` keeps its original export fragment in `raw` (stored in ES with
  `enabled: false`, not indexed; excluded from list/search/conversation queries, served by
  `/api/docs/{conversations|messages}/{id}`). Conversation `raw` omits the nested message list.
- `Message.parts` (optional, ES `enabled: false`): ordered blocks `text` / `thinking` / `tool`
  (input + matched output) / `summary` / `command` (slash or `!` shell command + its output,
  which arrives as the next user event) / `image` (`archive` zip path relative to the working
  dir + `member`; bytes are never indexed, `/api/images/{n}/{message_id}` reads them from the
  zip on demand), rendered with collapsed `<details>`. When present the
  template renders parts instead of `content`; `content` stays the searchable text only.
- `Conversation.project` (keyword): working directory for Claude Code sessions; drives the
  project filter in browse/search (`?project=`).
- Claude Code (`importers/claude_code.py`): `make sync-claude-code` rsyncs `~/.claude/projects/`
  into `data/raw/claude_code/<hostname>/` without `--delete` (Claude Code deletes old sessions).
  One assistant turn = all assistant events between two human prompts; tool results are matched
  by `tool_use_id` from the whole file (parallel calls put some results off the current branch);
  `subagents/*.jsonl` become separate `[subagent]` conversations.
- ChatGPT (`importers/chatgpt.py`): sharded `conversations-NNN.json` in the zip (`_io.load_json_all`),
  tree in `mapping` followed from `current_node`; consecutive assistant nodes (`thoughts` +
  answer) merge into one Message with parts; private-use citation markers (`\ue200…\ue201`) are
  stripped, entity markers replaced by their name.
- Gemini (`importers/gemini.py`): Takeout My Activity JSON = flat list of prompts (title with a
  localized prefix, `_PROMPT_PREFIX`) + answer HTML, converted to Markdown by a small stdlib
  parser; grouped into conversations by the `gemini.google.com/app/<id>` link. No model info.
- `src/chat_reflections/markdown.py` — message rendering (markdown-it, raw HTML escaped). Math
  (`$`, `$$`, `\(`, `\[`) is kept out of the markdown parser and rendered by KaTeX in the browser.
- `src/chat_reflections/web.py` — HTML views: `/` (per-source cards), `/browse/{source}` (two-pane:
  paginated list + `?c=<id>` conversation), `/search/{source}`; `source` is an importer name or
  `all`. JSON API under `/api/...`.

## Commands
- `make up` / `make down` — Elasticsearch on localhost:9200
- `make test` — unit tests (no ES); `make test-all` — includes `@pytest.mark.es` tests
  (use index prefix `test-chat`, skip if ES is down)
- `make lint` — ruff + pyright
- `make reindex` — rebuild indices from `data/raw`
- `make demo` — rebuild indices from `demo/raw` (synthetic, committed, copied into the app image;
  also used for README screenshots in `docs/`). Use `ES_PREFIX=demo` to avoid replacing real data.
- `make run` — dev server on localhost:8000
- `make sync-claude-code` — copy local Claude Code sessions into `data/raw`
- Docker (end users): `docker compose run --rm app chat-reflections reindex`, `docker compose up -d`.
  `data/` is mounted read-only, never baked into the image (`.dockerignore`).
- CI (`.github/workflows/ci.yml`): lint + all tests against ES from compose + app image build.
  With `CI` set, ES tests fail instead of skipping.

UI strings and docs are in English.

## Conventions
- IDs: conversation `"{source}:{external_id}"`, message `"{conversation_id}:{message_external_id}"`.
- Roles normalized to `user` / `assistant`. Skip messages with empty content.
- Branching chats (OpenWebUI, Claude Code, ChatGPT): index only the current branch (walk from
  current node / last message to root).
- Never commit or copy real data from `data/` into tests. Fixtures in `tests/fixtures/<source>/`
  are small synthetic files mirroring the real export structure.

## Adding an importer
1. Inspect the real export structure in `data/raw/<source>/` (keys/types only, don't dump content).
2. Write a synthetic fixture in `tests/fixtures/<source>/` covering edge cases (branches, empty
   messages, missing fields).
3. Implement `importers/<source>.py`, register it, add tests in `tests/test_importers.py`.
4. `make test lint`, then `make reindex` and check counts.

## Roadmap
- Semantic search: `dense_vector` field + local multilingual embeddings (e.g. multilingual-e5), hybrid with BM25
- MCP server exposing `search` / `get_conversation`
