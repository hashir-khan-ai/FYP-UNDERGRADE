# Corpus Expansion Guide & Regulatory Data Management

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Target User:** Hashir Khan  

---

## 1. Corpus Scale & Architecture Target

For retrieval ablation and benchmark metrics to achieve statistical significance, the corpus must be expanded beyond the minimal initial fixture:
- **Target Document Count:** 20 to 40 documents.
- **Target Chunk Count:** 200 to 500 chunks across the corpus.
- **Target Role Mix:**
  - **~65% Public / Unrestricted:** Accessible to all roles (`["analyst", "manager", "auditor"]`).
  - **~20% Management Restricted:** Accessible only to managers and auditors (`["manager", "auditor"]`).
  - **~15% Strictly Confidential Audit:** Accessible exclusively to auditors (`["auditor"]`).

---

## 2. Adding a Public Regulatory Document

Public documents belong in `data/raw/` (e.g., FCA Handbook sourcebooks, PRA rulebooks, BIS Basel standards, legislation).

### Step 2.1: Licensing & Source Verifications
- Only use authoritative, public-sector regulatory publications.
- Verify acceptable licensing:
  - **UK Crown Copyright / FCA / Legislation:** Open Government Licence v3.0 (UK OGL).
  - **BIS / Basel Committee:** Open academic and public information reuse.
  - **European Banking Authority (EBA) / EU:** EU public sector information reuse.
- Never ingest copyrighted textbooks, paywalled subscription summaries, or real bank client data.

### Step 2.2: File Naming & Markdown Structure
Save the file under `data/raw/<DESCRIPTIVE-NAME>.md` (e.g., `data/raw/FCA-SYSC-Senior-Management.md`).  
Structure the markdown with hierarchical headings (`#`, `##`, `###`) so `ClauseAwareChunker` generates clean `heading_path`s:

```markdown
# Financial Conduct Authority - Senior Management Arrangements, Systems and Controls (SYSC)

**Jurisdiction:** United Kingdom (FCA)
**Document ID:** DOC-FCA-SYSC-2024
**Classification:** Public Regulation
**Effective Date:** 2024-01-01
**Permitted Roles:** ["analyst", "manager", "auditor"]

---

## SYSC 4: General Organisational Requirements

### Clause SYSC-4.1.1R (General Requirements)
A firm must have robust governance arrangements, which include a clear organisational structure with well-defined, transparent and consistent lines of responsibility...
```

### Step 2.3: Companion Sidecar (`.meta.json`)
Every document in `data/raw/` must have a sidecar JSON named `<filename>.meta.json`:
```json
{
  "doc_id": "DOC-FCA-SYSC-2024",
  "title": "FCA Handbook: Senior Management Arrangements, Systems and Controls (SYSC)",
  "allowed_roles": ["analyst", "manager", "auditor"],
  "doc_type": "PUBLIC_REGULATION",
  "jurisdiction": "UK_FCA",
  "version": "2024.1",
  "source": "https://www.handbook.fca.org.uk/handbook/SYSC/",
  "licence": "Open Government Licence v3.0 (UK OGL)"
}
```

---

## 3. Authoring a Synthetic Internal Document

Synthetic documents belong in `data/synthetic/`. They simulate private bank policies, standard operating procedures (SOPs), and internal audit investigations.

### Rules for Synthetic Documents:
1. **Header Requirement:** Must prominently state `Classification: Internal ... (Synthetic)` and `SYNTHETIC_DATASET` in the source field.
2. **Strictly Zero Real Data:** Never include real employee names, live customer account numbers, or real commercial bank secrets.
3. **Role Assignment:**
   - Standard Operational SOPs: `["analyst", "manager", "auditor"]`
   - Supervisory Escalation / Management Policies: `["manager", "auditor"]`
   - Whistleblowing / Confidential Reviews / Committee Findings: `["auditor"]`
4. **Unique Role-Restricted Marker Facts:**
   - To keep automated leakage penetration tests mathematically rigorous ($0.00\%$ target), each role-restricted document must contain distinct numbers, code names, or policy triggers (e.g., *"Project Boreas"*, *"£750,000 threshold"*, *"Case WB-2025-11"*).
   - If an unauthorized query for analyst returns that marker fact, the penetration test immediately catches the data breach.

### Example Synthetic Document Template:
```markdown
# Bank Internal Policy: Capital Buffers & Liquidity Stress Management

**Document ID:** DOC-INT-POL-LIQ-003
**Classification:** Internal Management Policy (Synthetic)
**Version:** 1.0
**Owner:** Treasury & Risk Management Directorate
**Permitted Roles:** ["manager", "auditor"]
**Notice:** RESTRICTED INTERNAL POLICY. ACCESS CONFINED TO AUTHORIZED MANAGERS AND AUDITORS.

---

## Section 1: Liquidity Stress Contingency Triggers

### Clause POL-LIQ-1.1 (Severe Outflow Escalation)
If cumulative 5-day net liquidity outflows exceed 8% of eligible high-quality liquid assets (HQLA), the Head of Treasury must convene the Emergency Asset-Liability Committee within 4 hours.
```

Sidecar (`data/synthetic/POL-LIQ-003.meta.json`):
```json
{
  "doc_id": "DOC-INT-POL-LIQ-003",
  "title": "Bank Internal Policy: Capital Buffers & Liquidity Stress Management",
  "allowed_roles": ["manager", "auditor"],
  "doc_type": "INTERNAL_MANAGEMENT_POLICY",
  "jurisdiction": "INTERNAL_SYNTHETIC",
  "version": "1.0",
  "source": "SYNTHETIC_DATASET (FYP Liquidity Policy Fixture)",
  "licence": "Educational / Academic Final Year Project (BSc COM6301)"
}
```

---

## 4. Verification Workflow

After dropping in new documents:
1. **Scaffold blank sidecars:**
   ```powershell
   .\.venv\Scripts\python.exe scripts/corpus_manifest.py --add-template
   ```
2. **Audit metadata completeness:**
   ```powershell
   .\.venv\Scripts\python.exe scripts/corpus_manifest.py
   ```
3. **Re-index the entire corpus:**
   ```powershell
   $env:HF_HUB_OFFLINE="1"
   .\.venv\Scripts\python.exe src/ingestion/run.py --rebuild
   ```
4. **Verify RBAC isolation (must remain 0.00%):**
   ```powershell
   .\.venv\Scripts\python.exe scripts/leakage_check.py
   ```

