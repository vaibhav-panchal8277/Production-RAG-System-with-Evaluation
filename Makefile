.PHONY: help install install-backend install-frontend dev dev-backend dev-frontend docker-up docker-down docker-logs seed test clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# -----------------------------
# Local (no Docker) — needs Python 3.11 + Node 18+ + Yarn + MongoDB running
# -----------------------------

install: install-backend install-frontend ## Install backend + frontend deps

install-backend: ## Create .venv and install backend deps (CPU-only torch)
	python3.11 -m venv .venv
	./.venv/bin/pip install --upgrade pip
	./.venv/bin/pip install -r backend/requirements.txt
	./.venv/bin/pip uninstall -y torch || true
	./.venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1

install-frontend: ## Install frontend deps with Yarn
	cd frontend && yarn install

dev-backend: ## Run FastAPI with auto-reload
	cd backend && ../.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001 --reload

dev-frontend: ## Run React dev server
	cd frontend && yarn start

dev: ## Print the two commands to run in separate terminals
	@echo "Run these in two terminals:"
	@echo "  1) make dev-backend"
	@echo "  2) make dev-frontend"

# -----------------------------
# Docker
# -----------------------------

docker-up: ## Build & start Mongo + backend + frontend in Docker
	docker compose up --build

docker-down: ## Stop containers
	docker compose down

docker-logs: ## Tail Docker logs
	docker compose logs -f

# -----------------------------
# Utilities
# -----------------------------

seed: ## Seed the sample corpus via the running backend
	curl -sS -X POST http://localhost:8001/api/documents/seed | python3 -m json.tool

test: ## Run backend pytest suite
	cd backend && ../.venv/bin/pytest -q

clean: ## Remove caches and node_modules
	rm -rf .venv frontend/node_modules **/__pycache__ .pytest_cache .ruff_cache
