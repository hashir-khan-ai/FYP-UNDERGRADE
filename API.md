# REST API Specification

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Protocol:** HTTP/1.1 (RESTful JSON)  
**Base URL:** `http://127.0.0.1:8000`  
**Status:** Frozen Scope Baseline (Updated with Resilient LLM Wrapper & Quota Protection)  

---

## 1. Global Conventions & Error Standards

### 1.1 Content Negotiation & Security
- All requests and responses must use `Content-Type: application/json`.
- Authentication via Bearer token: `Authorization: Bearer <jwt_or_user_token>`.
- Cross-Origin Resource Sharing (CORS) is restricted strictly to `http://localhost:8501` and `http://127.0.0.1:8501` (Streamlit UI).
- Sensitive headers and credentials are never reflected in error bodies or logged.

### 1.2 Error Response Format
All errors return a standard JSON envelope with appropriate HTTP status codes. Internal stack traces are never exposed to clients:

```json
{
  "error": {
    "code": "STRING_IDENTIFIER",
    "message": "User-friendly, actionable description of the issue.",
    "details": null
  }
}
```

### 1.3 Common HTTP Status Codes
- `200 OK`: Request succeeded.
- `201 Created`: Resource successfully created.
- `400 Bad Request`: Malformed payload or business rule violation.
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: Authenticated user role has insufficient permissions for this endpoint.
- `404 Not Found`: Requested resource (session, message, user) does not exist.
- `422 Unprocessable Entity`: Pydantic validation failure.
- `429 Too Many Requests`: Client-side rate limiter, spend guard (`code: LLM_SPEND_LIMIT`), or upstream API rate limit hit.
- `503 Service Unavailable`: Both primary and fallback cloud LLM providers are offline.

---

## 2. API Endpoints Overview

| Method | Path | Summary | Access Level |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/login` | Authenticate synthetic user, return token | Public |
| `GET` | `/api/v1/auth/users` | List synthetic users for test switching | Public (Dev mode) |
| `GET` | `/api/v1/auth/me` | Return profile and role of authenticated user | Any Authenticated |
| `POST` | `/api/v1/chat/query` | Submit compliance query and execute RAG pipeline | Any Authenticated |
| `GET` | `/api/v1/sessions` | List active chat sessions for authenticated user | Any Authenticated |
| `POST` | `/api/v1/sessions` | Create a new chat session | Any Authenticated |
| `GET` | `/api/v1/sessions/{id}/messages` | Retrieve conversation turn history for a session | Session Owner |
| `DELETE` | `/api/v1/sessions/{id}` | Delete a chat session and its messages | Session Owner |
| `GET` | `/api/v1/audit/logs` | Fetch immutable audit trail with filtering | **Auditor Role Only** |
| `GET` | `/api/v1/admin/health` | Check health of cloud LLM providers, cache, SQLite, Qdrant | Any Authenticated |
| `POST` | `/api/v1/admin/ingest` | Trigger corpus ingestion and indexing | Admin / CLI |
| `GET` | `/api/v1/admin/config` | Read active profile, layer flags, model, prompt version, and spend caps | Any Authenticated |

---

## 3. Endpoint Specifications

### 3.1 Authentication

#### `POST /api/v1/auth/login`
Authenticates a synthetic user and generates a session JWT.

- **Request Body (`LoginRequest`):**
```json
{
  "username": "analyst_user",
  "password": "password123"
}
```

- **Response (`LoginResponse` - 200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "analyst_user",
    "full_name": "Alice Analyst",
    "role": "analyst"
  }
}
```

---

### 3.2 Chat & Compliance RAG Engine

#### `POST /api/v1/chat/query`
The primary operational endpoint. Executes the configured RAG pipeline with caching, rate limiting, and fallback handling.

- **Request Body (`ChatQueryRequest`):**
```json
{
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "query": "What are the KYC verification requirements for high-risk corporate clients?",
  "config_overrides": {
    "enable_adaptive_router": true,
    "enable_corrective_grader": true,
    "enable_rbac_memory": true,
    "enable_xai_output": true
  }
}
```

- **Response Body (`ChatQueryResponse` - 200 OK):**
```json
{
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "answer": "Under Regulation 12(3)(a) of the Money Laundering Regulations 2017, relevant persons must apply enhanced customer due diligence (EDD) for high-risk corporate clients. This requires verifying beneficial ownership down to 25% voting rights and establishing the source of wealth.",
  "route_taken": "SINGLE_SEARCH",
  "citations": [
    {
      "doc_id": "DOC-FCA-MLR-2017",
      "doc_name": "Money Laundering Regulations 2017",
      "section_title": "Section 4: Customer Due Diligence Measures",
      "clause_id": "Regulation 12(3)(a)",
      "page_number": 14,
      "snippet": "A relevant person must apply customer due diligence measures where..."
    }
  ],
  "reasoning_trace": [
    "Step 1: Router classified query as SINGLE_SEARCH.",
    "Step 2: RBAC filter applied for role 'analyst'.",
    "Step 3: Hybrid search retrieved 20 candidates; Cross-Encoder scored top-5.",
    "Step 4: Corrective Grader scored top chunks (score 0.92 >= 0.65 threshold). Passed without retry.",
    "Step 5: Generator synthesized answer cited to Regulation 12(3)(a)."
  ],
  "retrieval_stats": {
    "total_chunks_retrieved": 5,
    "top_rerank_score": 0.884,
    "retry_count": 0,
    "rewritten_query": null
  },
  "llm_stats": {
    "profile": "dev",
    "model": "llama-3.1-8b-instant",
    "prompt_version": "v1",
    "calls": 1,
    "cached_calls": 0,
    "prompt_tokens": 420,
    "completion_tokens": 78,
    "cached_response": false
  },
  "spend": {
    "calls_used": 1,
    "calls_limit": 40,
    "tokens_used": 498,
    "tokens_limit": 120000,
    "exhausted": false
  },
  "latency_ms": 1120.5,
  "audit_id": 1042
}
```

---

### 3.3 Audit Trail (Auditor Role Enforced)

#### `GET /api/v1/audit/logs`
Allows an auditor to review all queries, routes, retrieved chunks, and reasoning traces.

- **Security Constraint:** Returns `403 Forbidden` if caller role is `analyst` or `manager`.
- **Query Parameters:**
  - `limit`: int (default 50, max 200)
  - `user_id`: optional int
  - `start_date`: optional ISO timestamp
- **Response (200 OK):**
```json
[
  {
    "audit_id": 1042,
    "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "user_id": 1,
    "user_role": "analyst",
    "query_text": "What are the KYC verification requirements for high-risk corporate clients?",
    "final_route": "SINGLE_SEARCH",
    "retrieved_chunk_ids": ["FCA-MLR-2017_SEC4_CL12"],
    "retry_count": 0,
    "response_text": "Under Regulation 12(3)(a)...",
    "latency_ms": 1120.5,
    "created_at": "2026-11-11T12:30:12Z"
  }
]
```

---

### 3.4 System Administration & Health

#### `GET /api/v1/admin/health`
Checks cloud LLM providers, local models, and storage health.

- **Response (200 OK):**
```json
{
  "status": "healthy",
  "llm_gateway": {
    "active_profile": "dev",
    "mock_mode": false,
    "provider": {
      "name": "Groq",
      "model": "llama-3.1-8b-instant",
      "status": "online"
    },
    "fallback_provider": {
      "name": "OpenRouter",
      "model": "meta-llama/llama-3.1-8b-instruct:free",
      "status": "online"
    },
    "cache": {
      "status": "active",
      "total_entries": 48
    },
    "spend_guard": {
      "calls_limit": 40,
      "tokens_limit": 120000,
      "calls_used_current_run": 3,
      "tokens_used_current_run": 498
    }
  },
  "local_models": {
    "embeddings": "BAAI/bge-small-en-v1.5 (CPU)",
    "reranker": "cross-encoder/ms-marco-MiniLM-L-6-v2 (CPU)"
  },
  "vector_store": {
    "status": "online",
    "mode": "qdrant_embedded",
    "collection": "compliance_chunks",
    "total_vectors": 850
  },
  "database": {
    "status": "online",
    "engine": "sqlite",
    "wal_enabled": true
  }
}
```

---

## 4. Pydantic v2 Models Definition (`src/api/schemas.py`)

```python
from pydantic import BaseModel, Field
from typing import Optional

# Auth Models
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)

class UserProfile(BaseModel):
    id: int
    username: str
    full_name: str
    role: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile

# Config Overrides for Ablation
class ConfigOverrides(BaseModel):
    enable_adaptive_router: Optional[bool] = None
    enable_corrective_grader: Optional[bool] = None
    enable_rbac_memory: Optional[bool] = None
    enable_xai_output: Optional[bool] = None

# Citation Model
class Citation(BaseModel):
    doc_id: str
    doc_name: str
    section_title: str
    clause_id: str
    page_number: Optional[int] = None
    snippet: str

# LLM Stats
class LLMStats(BaseModel):
    profile: str                      # 'mock' | 'dev' | 'demo'
    model: str
    prompt_version: str
    calls: int
    cached_calls: int
    prompt_tokens: int
    completion_tokens: int
    cached_response: bool

class SpendStats(BaseModel):
    calls_used: int
    calls_limit: int
    tokens_used: int
    tokens_limit: int
    exhausted: bool

# Chat Query Models
class ChatQueryRequest(BaseModel):
    session_id: str = Field(..., description="UUIDv4 session identifier")
    query: str = Field(..., min_length=2, max_length=2000)
    config_overrides: Optional[ConfigOverrides] = None

class RetrievalStats(BaseModel):
    total_chunks_retrieved: int
    top_rerank_score: float
    retry_count: int
    rewritten_query: Optional[str] = None

class ChatQueryResponse(BaseModel):
    session_id: str
    answer: str
    route_taken: str
    citations: list[Citation]
    reasoning_trace: list[str]
    retrieval_stats: RetrievalStats
    llm_stats: LLMStats
    spend: SpendStats
    latency_ms: float
    audit_id: int

# Error Envelope Model
class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[dict] = None

class ErrorResponse(BaseModel):
    error: ErrorDetail
```
