# Contributing Guidelines

Thank you for your interest in contributing to the Enterprise RAG Assistant for Banking Regulatory Compliance.

---

## 1. Development Principles

1. **Academic Rigor & Simplicity:** Prioritize correctness, clean module boundaries, strict testability, and zero over-engineering.
2. **Deterministic Mock Testing ($0 Quota Spend):** All automated unit and integration tests must execute under the `mock` profile without network calls.
3. **Zero Unauthorized Leakage:** Any change affecting retrieval must pass automated penetration tests (`scripts/leakage_check.py --real-index`) with $0.00\%$ leakage.
4. **No Weakening of Existing Tests:** Never remove or loosen assertions without an explicit, documented architectural justification.

---

## 2. Setting Up the Environment

```bash
# 1. Clone the repository
git clone https://github.com/hashir-khan/FYP-UNDERGRADE.git
cd FYP-UNDERGRADE

# 2. Create virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Initialize test database and index corpus
python scripts/seed_data.py
python -m src.ingestion.run --rebuild
```

---

## 3. Pre-Commit Verification Checklist

Before submitting a pull request, ensure the following commands pass with zero errors:

```bash
# Run complete test suite
pytest -v

# Run penetration leakage suite against real index
python scripts/leakage_check.py --real-index

# Run adversarial red team suite
python scripts/eval_redteam.py

# Verify audit log cryptographic integrity
python scripts/verify_audit.py

# Verify zero secrets in tracked files
python scripts/scan_secrets.py
```

---

## 4. Conventional Commit Standards

Please use standard conventional commit syntax:
- `feat:` for new pipeline capabilities or architectural layers
- `fix:` for bug fixes
- `test:` for test additions or verification scripts
- `docs:` for documentation updates
- `refactor:` for internal improvements without feature changes

