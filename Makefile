# VEYRA task runner (Linux / macOS / WSL2)
API_DIR := apps/api

.PHONY: help install api-dev web-dev test test-api test-web lint lint-api lint-web gen-api migrate up down

help:
	@echo "install | api-dev | web-dev | test | lint | gen-api | migrate | up | down"

install:
	pnpm install
	cd $(API_DIR) && uv sync

api-dev:
	cd $(API_DIR) && uv run uvicorn app.main:app --reload --port 8000

web-dev:
	pnpm --filter @veyra/web dev

test: test-api test-web

test-api:
	cd $(API_DIR) && uv run pytest

test-web:
	pnpm -r test

lint: lint-api lint-web

lint-api:
	cd $(API_DIR) && uv run ruff check . && uv run ruff format --check . && uv run mypy app

lint-web:
	pnpm -r lint && pnpm -r typecheck

# Export OpenAPI from the API, then regenerate the typed TS client.
gen-api:
	cd $(API_DIR) && uv run python -m app.scripts.export_openapi ../../packages/api-client/openapi.json
	pnpm --filter @veyra/api-client generate

migrate:
	cd $(API_DIR) && uv run alembic upgrade head

up:
	docker compose -f infra/docker-compose.yml up --build -d

down:
	docker compose -f infra/docker-compose.yml down
