# Regulatory Data Provenance, Licensing & Corpus Governance

This document describes the provenance, licensing conditions, and synthetic fixtures within the regulatory compliance corpus.

---

## 1. Corpus Architecture & Separation

The regulatory corpus is strictly divided into two categories:
1. **Public Statutory & Regulatory Frameworks** (`data/raw/`): Authoritative public guidance issued by government and supervisory authorities (UK FCA, PRA, BCBS, UK Parliament).
2. **Synthetic Internal Banking Policies & SOPs** (`data/synthetic/`): Artificially generated operational procedures, management incident escalation frameworks, and confidential audit review findings used strictly to evaluate Role-Based Access Control (RBAC) filtering and isolation.

---

## 2. Public Regulatory Documents Provenance

| Document ID | Source Title | Authority / Jurisdiction | Publication Year | Licence / Terms | Redistribution Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `DOC-UK-MLR-2017` | Money Laundering, Terrorist Financing and Transfer of Funds Regulations 2017 | UK Parliament / Legislation.gov.uk | 2017 | Open Government Licence v3.0 | Permitted freely under OGL v3.0 |
| `DOC-UK-GDPR-2018` | Data Protection Act 2018 / UK GDPR | UK Parliament / Legislation.gov.uk | 2018 | Open Government Licence v3.0 | Permitted freely under OGL v3.0 |
| `DOC-UK-TACT-2000` | Terrorism Act 2000 & Sanctions Regulations 2018 | UK Parliament / Legislation.gov.uk | 2000 / 2018 | Open Government Licence v3.0 | Permitted freely under OGL v3.0 |
| `DOC-FCA-BCOBS-2024` | Banking: Conduct of Business Sourcebook (BCOBS) | Financial Conduct Authority (FCA) | 2024 | Crown Copyright / FCA Terms | Research & academic study fair dealing |
| `DOC-FCA-SYSC-2024` | Senior Management Arrangements, Systems and Controls (SYSC) | Financial Conduct Authority (FCA) | 2024 | Crown Copyright / FCA Terms | Research & academic study fair dealing |
| `DOC-FCA-CASS-2024` | Client Assets Sourcebook (CASS) | Financial Conduct Authority (FCA) | 2024 | Crown Copyright / FCA Terms | Research & academic study fair dealing |
| `DOC-FCA-PRIN-2024` | Principles for Businesses (PRIN) | Financial Conduct Authority (FCA) | 2024 | Crown Copyright / FCA Terms | Research & academic study fair dealing |
| `DOC-FCA-COBS-2024` | Conduct of Business Sourcebook (COBS) | Financial Conduct Authority (FCA) | 2024 | Crown Copyright / FCA Terms | Research & academic study fair dealing |
| `DOC-FCA-CONC-2024` | Consumer Credit Sourcebook (CONC) | Financial Conduct Authority (FCA) | 2024 | Crown Copyright / FCA Terms | Research & academic study fair dealing |
| `DOC-FCA-DISP-2024` | Dispute Resolution: Complaints (DISP) | Financial Conduct Authority (FCA) | 2024 | Crown Copyright / FCA Terms | Research & academic study fair dealing |
| `DOC-FCA-MAR-2024` | Market Conduct Sourcebook (MAR) | Financial Conduct Authority (FCA) | 2024 | Crown Copyright / FCA Terms | Research & academic study fair dealing |
| `DOC-PRA-SS121-2021` | Supervisory Statement SS1/21: Operational Resilience | Prudential Regulation Authority (PRA) | 2021 | Bank of England Crown Copyright | Research & academic study fair dealing |
| `DOC-PRA-SS221-2021` | Supervisory Statement SS2/21: Outsourcing & Third Party Risk | Prudential Regulation Authority (PRA) | 2021 | Bank of England Crown Copyright | Research & academic study fair dealing |
| `DOC-BASEL-III-2023` | Basel III: International Regulatory Framework for Banks | Basel Committee on Banking Supervision (BCBS) | 2023 | BIS Copyright (Unverified commercial redistribution) | Academic & research quotation |
| `DOC-BASEL-FRTB-2023`| Fundamental Review of the Trading Book (FRTB) | Basel Committee on Banking Supervision (BCBS) | 2023 | BIS Copyright (Unverified commercial redistribution) | Academic & research quotation |
| `DOC-EBA-GL-2021` | EBA Guidelines on ML/TF Risk Factors (EBA/GL/2021/02) | European Banking Authority (EBA) | 2021 | EBA Copyright / Public Domain Guidance | Academic & research quotation |

---

## 3. Synthetic Internal Policies (100% Synthetic)

All files under `data/synthetic/` are explicitly marked with `content_origin: "synthetic"` and possess zero real confidential banking data:
- `SOP-KYC-CDD-001.md`: Operational procedures for Customer Due Diligence and PEP identification. Permitted: `analyst`, `manager`, `auditor`.
- `SOP-TRANSACTION-MONITORING-002.md`: Automated AML transaction monitoring thresholds and SAR escalation. Permitted: `analyst`, `manager`, `auditor`.
- `SOP-VULNERABLE-CUSTOMERS-003.md`: Operational guidance for identifying customer vulnerability indicators. Permitted: `analyst`, `manager`, `auditor`.
- `POLICY-SUPERVISORY-ESCALATION-002.md`: Incident escalation and £500,000 threshold for Senior Management Regime. Permitted: `manager`, `auditor`.
- `POLICY-CYBER-INCIDENT-ESCALATION-003.md`: Critical cyber incident Severity 1 response and 4-hour regulatory notification. Permitted: `manager`, `auditor`.
- `POLICY-MARKET-ABUSE-SURVEILLANCE-004.md`: Market abuse surveillance, insider lists, and personal account dealing rules. Permitted: `manager`, `auditor`.
- `AUDIT-CONFIDENTIAL-FINDINGS-2025.md`: Confidential review of intra-month liquidity buffer deficits. Permitted: `auditor` only.
- `AUDIT-CYBER-PENETRATION-FINDINGS-2025.md`: Confidential review of payment gateway cryptographic defects. Permitted: `auditor` only.

