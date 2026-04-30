# ─────────────────────────────────────────────────────────────────────────────
# Test Triage Tool — Makefile
# Shortcuts for common developer and operator tasks.
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: help setup run run-docker build-docker stop-docker clean test lint \
        sample-json sample-xml

# Default target
help:
	@echo ""
	@echo " Test Triage Tool — available commands"
	@echo ""
	@echo "  Local development"
	@echo "  ─────────────────────────────────────────"
	@echo "  make setup        Install dependencies + copy .env.example"
	@echo "  make run          Start Streamlit UI locally"
	@echo "  make test         Run full test suite"
	@echo "  make lint         Run ruff linter"
	@echo ""
	@echo "  Docker"
	@echo "  ─────────────────────────────────────────"
	@echo "  make build-docker Build Docker image"
	@echo "  make run-docker   Start with docker compose"
	@echo "  make stop-docker  Stop and remove containers"
	@echo "  make logs         Tail container logs"
	@echo ""
	@echo "  Demo"
	@echo "  ─────────────────────────────────────────"
	@echo "  make sample-json  Run CLI triage on JSON sample"
	@echo "  make sample-xml   Run CLI triage on XML sample"
	@echo ""

# ── Local dev ─────────────────────────────────────────────────────────────────

setup:
	@echo "→ Installing dependencies..."
	pip install -r requirements.txt
	@if [ ! -f .env ]; then \
	  cp .env.example .env; \
	  echo "→ Created .env from .env.example — add your ANTHROPIC_API_KEY"; \
	else \
	  echo "→ .env already exists — skipping"; \
	fi
	@mkdir -p data/runs data/samples
	@python -c "import sys; sys.path.insert(0,'.'); import db.store as s; s.init_db()"
	@echo "→ Setup complete."

run:
	@echo "→ Starting Streamlit UI on http://localhost:8501"
	streamlit run ui/app.py

test:
	@echo "→ Running test suite..."
	pytest tests/ -v --tb=short

lint:
	@echo "→ Running ruff linter..."
	ruff check . --fix

# ── Docker ────────────────────────────────────────────────────────────────────

build-docker:
	@echo "→ Building Docker image..."
	docker compose build

run-docker:
	@echo "→ Starting with docker compose..."
	@echo "   UI will be available at http://localhost:8501"
	docker compose up -d
	@echo "→ Run 'make logs' to tail output"

stop-docker:
	@echo "→ Stopping containers..."
	docker compose down

logs:
	docker compose logs -f triage-ui

# ── Demo shortcuts ────────────────────────────────────────────────────────────

sample-json:
	python -m cli.main analyse samples/pppoe_vlan_mismatch.json --no-exec

sample-xml:
	python -m cli.main analyse samples/pppoe_vlan_mismatch.xml --no-exec

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache
	@echo "→ Clean done."
