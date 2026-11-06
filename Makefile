.PHONY: install up down test test-all lint reindex demo run sync-claude-code

# optional local settings, e.g. CHAT_LANGUAGES=polish,english (also read by docker compose)
-include .env
export

install:
	uv sync

# dev: only Elasticsearch; the app runs on the host via `make run`
up:
	docker compose up -d --build es

down:
	docker compose down

test:
	uv run pytest -m "not es"

test-all:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check . && uv run pyright

reindex:
	uv run chat-reflections reindex

# replaces the index with synthetic demo conversations; `make reindex` brings your data back
demo:
	uv run chat-reflections reindex --raw-dir demo/raw

run:
	uv run uvicorn chat_reflections.web:app --reload

# no --delete: sessions removed by Claude Code's cleanup stay in the archive
sync-claude-code:
	rsync -a ~/.claude/projects/ data/raw/claude_code/$$(hostname)/
