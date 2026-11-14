# Third-Party Dependencies, Models, and Datasets

This document catalogues all third-party software packages, pre-trained neural models, and external data sources used by the Enterprise RAG Assistant.

---

## 1. Python Software Dependencies

| Package | Version | Licence | Verified Licence URL | Notes / Usage |
| :--- | :--- | :--- | :--- | :--- |
| **fastapi** | 0.115.6 | MIT | https://github.com/fastapi/fastapi/blob/master/LICENSE | REST API routing and OpenAPI documentation |
| **uvicorn** | 0.34.0 | BSD-3-Clause | https://github.com/encode/uvicorn/blob/master/LICENSE.md | ASGI production application server |
| **python-multipart** | 0.0.20 | Apache-2.0 | https://github.com/Kludex/python-multipart/blob/main/LICENSE.txt | Form parsing support for FastAPI endpoints |
| **pydantic** | 2.10.4 | MIT | https://github.com/pydantic/pydantic/blob/main/LICENSE | Data validation and JSON schema enforcement |
| **pydantic-settings**| 2.7.1 | MIT | https://github.com/pydantic/pydantic-settings/blob/main/LICENSE | Type-safe environment configuration from `.env` |
| **argon2-cffi** | 25.1.0 | MIT | https://github.com/hynek/argon2-cffi/blob/main/LICENSE | Password hashing for local demo credentials |
| **httpx** | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx/blob/master/LICENSE.md | Resilient HTTP client for LLM provider gateway |
| **qdrant-client** | 1.12.1 | Apache-2.0 | https://github.com/qdrant/qdrant-client/blob/master/LICENSE | Embedded vector database with native RBAC filtering |
| **rank-bm25** | 0.2.2 | Apache-2.0 | https://github.com/dorianbrown/rank_bm25/blob/master/LICENSE | Lexical BM25 search engine for hybrid retrieval |
| **sentence-transformers** | 3.3.1 | Apache-2.0 | https://github.com/UKPLab/sentence-transformers/blob/master/LICENSE | Local CPU inference for embeddings and re-ranking |
| **langchain-core** | 0.3.29 | MIT | https://github.com/langchain-ai/langchain/blob/master/libs/core/LICENSE | Prompt abstractions and message schemas |
| **langgraph** | 0.2.60 | MIT | https://github.com/langchain-ai/langgraph/blob/main/LICENSE | State machine execution for corrective retries |
| **pypdf** | 5.1.0 | BSD-3-Clause | https://github.com/py-pdf/pypdf/blob/main/LICENSE | Text extraction for regulatory PDF documents |
| **beautifulsoup4** | 4.12.3 | MIT | https://git.launchpad.net/beautifulsoup/tree/LICENSE | HTML parsing and table extraction |

---

## 2. Pre-Trained Machine Learning Models

| Model Identifier | Architecture | Licence | Verified Source URL | Resource Footprint |
| :--- | :--- | :--- | :--- | :--- |
| **BAAI/bge-small-en-v1.5** | Dense Embedding (dim=384) | MIT | https://huggingface.co/BAAI/bge-small-en-v1.5 | ~130MB weights, CPU execution |
| **cross-encoder/ms-marco-MiniLM-L-6-v2** | Cross-Encoder Re-ranker | Apache-2.0 | https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2 | ~80MB weights, CPU execution |

---

## 3. Regulatory Corpora & Provenance

| Document Source | Jurisdictional Origin | Licence / Rights Notice | Redistribution Terms |
| :--- | :--- | :--- | :--- |
| **UK Statutory Instruments** (MLR 2017, Data Protection Act 2018) | United Kingdom (Legislation.gov.uk) | Open Government Licence v3.0 | Freely redistributable with attribution under OGL v3.0 |
| **FCA Handbook** (BCOBS, SYSC, CASS, PRIN, COBS, CONC, DISP, MAR) | Financial Conduct Authority (UK) | Crown Copyright / FCA Terms (unverified for commercial redistribution) | Academic research exemption under UK Copyright, Designs and Patents Act 1988 (Section 29) |
| **PRA Supervisory Statements** (SS1/21, SS2/21) | Bank of England / PRA | Crown Copyright / Bank of England Terms | Educational / academic dissertation fair dealing |
| **Basel III Capital & Liquidity Framework** | Bank for International Settlements (BCBS) | BIS Copyright (unverified commercial redistribution) | Public international standards, educational quotation |
| **Internal Bank Policies & SOPs** (`data/synthetic/`) | Project Author (Hashir Khan) | MIT | 100% Synthetic fixtures created for testing RBAC |

---

## 4. Next.js Frontend Software Dependencies

| Package | Version | Licence | Verified Licence URL | Notes / Usage |
| :--- | :--- | :--- | :--- | :--- |
| **next** | 16.4.6 | MIT | https://github.com/vercel/next.js/blob/canary/license.md | React framework with App Router, Turbopack, and SSR |
| **react** | 19.3.1 | MIT | https://github.com/facebook/react/blob/main/LICENSE | Core UI component runtime |
| **react-dom** | 19.3.1 | MIT | https://github.com/facebook/react/blob/main/LICENSE | DOM rendering engine for React |
| **@radix-ui/react-dialog** | 1.3.1 | MIT | https://github.com/radix-ui/primitives/blob/main/LICENSE | Accessible headless dialog & modal primitive |
| **@radix-ui/react-dropdown-menu** | 2.2.1 | MIT | https://github.com/radix-ui/primitives/blob/main/LICENSE | Accessible dropdown menu primitive |
| **@radix-ui/react-tooltip** | 1.4.1 | MIT | https://github.com/radix-ui/primitives/blob/main/LICENSE | Accessible tooltip provider & portal |
| **@radix-ui/react-collapsible** | 1.2.1 | MIT | https://github.com/radix-ui/primitives/blob/main/LICENSE | Accessible collapsible layout primitive |
| **@radix-ui/react-slot** | 1.3.1 | MIT | https://github.com/radix-ui/primitives/blob/main/LICENSE | Polymorphic `asChild` composition helper |
| **lucide-react** | 1.72.0 | ISC | https://github.com/lucide-icons/lucide/blob/main/LICENSE | Accessible vector icon set |
| **sonner** | 2.0.8 | MIT | https://github.com/emilkowalski/sonner/blob/main/LICENSE | Toast notification dispatcher |
| **tailwindcss** | 4.3.5 | MIT | https://github.com/tailwindlabs/tailwindcss/blob/main/LICENSE | Utility-first CSS engine |
| **clsx** | 2.1.1 | MIT | https://github.com/lukeed/clsx/blob/master/license | Conditional className utility |
| **tailwind-merge** | 3.7.0 | MIT | https://github.com/dcastil/tailwind-merge/blob/v3.7.0/LICENSE | Intelligent Tailwind class conflict resolver |
| **framer-motion** | 14.13.0 | MIT | https://github.com/motiondivision/motion/blob/main/LICENSE.md | Physics-based fluid transition engine |
| **react-markdown** | 10.1.0 | MIT | https://github.com/remarkjs/react-markdown/blob/main/license | Safe Markdown rendering component |
| **remark-gfm** | 4.0.1 | MIT | https://github.com/remarkjs/remark-gfm/blob/main/license | GitHub Flavored Markdown plugin |
| **axe-core** | 4.14.0 | MPL-2.0 | https://github.com/dequelabs/axe-core/blob/develop/LICENSE | Official automated WCAG accessibility test engine |

