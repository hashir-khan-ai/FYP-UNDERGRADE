.PHONY: help install seed index test leakage redteam verify-audit run-api scan-secrets docker-up docker-down

help:
	@echo "Available commands:"
	@echo "  install      Install pinned dependencies"
	@echo "  seed         Seed SQLite database with roles, users, and documents"
	@echo "  index        Rebuild Qdrant vector store and BM25 index"
	@echo "  test         Run complete automated test suite in mock mode"
	@echo "  leakage      Execute automated penetration tests on real index (0.00% leakage target)"
	@echo "  redteam      Execute 45-case adversarial red team evaluation suite"
	@echo "  verify-audit Verify cryptographic hash chain of SQLite audit_log"
	@echo "  scan-secrets Scan repo and git history for API keys or secrets"
	@echo "  run-api      Start FastAPI backend server (http://127.0.0.1:8000)"
	@echo "  docker-up    Build and run API in Docker container"
	@echo "  docker-down  Stop Docker containers"

install:
	pip install -r requirements.txt

seed:
	python scripts/seed_data.py

index:
	python -m src.ingestion.run --rebuild

test:
	pytest -v

leakage:
	python scripts/leakage_check.py --real-index

redteam:
	python scripts/eval_redteam.py

verify-audit:
	python scripts/verify_audit.py

scan-secrets:
	python scripts/scan_secrets.py

run-api:
	uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

