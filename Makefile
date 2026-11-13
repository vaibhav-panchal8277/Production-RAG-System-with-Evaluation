.PHONY: help install install-backend install-frontend install-streamlit dev dev-backend dev-frontend docker-up docker-down docker-logs seed test clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# -----------------------------
# Local (no Docker) — needs Python 3.11 + Node 18+ + Yarn + MongoDB running
# -----------------------------

install: install-backend install-frontend ## Install backend + frontend deps

install-backend: ## Create .venv and install backend + dev deps
	python3.11 -m venv .venv
	./.venv/bin/pip install --upgrade pip
	./.venv/bin/pip install -r backend/requirements-dev.txt

install-streamlit: ## Install the Streamlit UI deps into .venv
	./.venv/bin/pip install -r requirements-streamlit.txt

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

BACKEND_URL ?= http://localhost:8001

# Sends X-API-Key when RAG_API_KEY is set in the shell or in backend/.env
# (seeding is an authenticated route once a key is configured).
seed: ## Seed the sample corpus via the running backend
	@KEY="$${RAG_API_KEY:-$$(sed -n 's/^RAG_API_KEY=//p' backend/.env 2>/dev/null)}"; \
	curl -sS -X POST $${KEY:+-H "X-API-Key: $$KEY"} $(BACKEND_URL)/api/documents/seed | python3 -m json.tool

test: ## Run backend pytest suite
	cd backend && ../.venv/bin/pytest -q

clean: ## Remove caches and node_modules
	rm -rf .venv frontend/node_modules **/__pycache__ .pytest_cache .ruff_cache
