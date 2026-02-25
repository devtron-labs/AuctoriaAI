# AuctoriaAI — AI-Powered Document Governance Platform

AuctoriaAI is a full-stack governance platform that enforces quality, accuracy, and compliance for AI-generated documents. It implements a structured multi-stage pipeline where every document travels through automated fact extraction, LLM-powered draft generation, rubric-based QA evaluation, claim validation, and human review — all with full audit trails.

## Recent Updates

**Multi-Provider LLM Support** (February 2026)
- Added support for multiple LLM providers: Anthropic, OpenAI, Google AI, xAI, and Perplexity
- New `llm_adapter.py` service automatically routes requests to the correct provider based on model name
- Runtime-configurable API keys for all providers via Admin Settings
- Model selection now includes GPT-4, Gemini, Grok, and other models alongside Claude
- Backwards compatible: Anthropic `ANTHROPIC_API_KEY` environment variable still supported

---

## Table of Contents

- [Recent Updates](#recent-updates)
1. [Problem Statement](#1-problem-statement)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Document Lifecycle Pipeline](#3-document-lifecycle-pipeline)
4. [Technology Stack](#4-technology-stack)
5. [Project Structure](#5-project-structure)
6. [Database Schema](#6-database-schema)
7. [API Reference](#7-api-reference)
8. [Services & Business Logic](#8-services--business-logic)
9. [Governance Gates & Safety Mechanisms](#9-governance-gates--safety-mechanisms)
10. [Configuration & Environment](#10-configuration--environment)
11. [Frontend Architecture](#11-frontend-architecture)
12. [Running Locally](#12-running-locally)
13. [Database Migrations](#13-database-migrations)
14. [Testing](#14-testing)
15. [Deployment Considerations](#15-deployment-considerations)
16. [Key Design Decisions](#16-key-design-decisions)

---

## 1. Problem Statement

Enterprise teams using LLMs to generate whitepapers, technical documents, and compliance reports face three core risks:

1. **Hallucinations** — AI generates unsupported or false claims.
2. **Unverified integrations/compliance** — Documents claim integrations or certifications that don't exist in the official record.
3. **No governance trail** — Generated content bypasses review processes, causing regulatory exposure.

AuctoriaAI solves this with an automated pipeline: documents are factually grounded before generation, validated against an approved claim registry, scored by rubric, and routed to human reviewers before any document is approved for release.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AuctoriaAI Platform                           │
│                                                                     │
│  ┌──────────────────┐         ┌──────────────────────────────────┐  │
│  │  React Frontend  │◄───────►│      FastAPI Backend             │  │
│  │  (TypeScript 19) │  REST   │      (Python 3.x)                │  │
│  │  Port: 5173      │  JSON   │      Port: 8000                  │  │
│  └──────────────────┘         └──────────────┬───────────────────┘  │
│                                              │                      │
│                               ┌─────────────▼─────────────┐        │
│                               │    Service Layer           │        │
│                               │  ┌─────────────────────┐  │        │
│                               │  │  document_service   │  │        │
│                               │  │  extraction_service │  │        │
│                               │  │  draft_generation   │  │        │
│                               │  │  qa_iteration       │  │        │
│                               │  │  claim_validation   │  │        │
│                               │  │  governance_service │  │        │
│                               │  │  review_service     │  │        │
│                               │  └─────────────────────┘  │        │
│                               └─────────────┬─────────────┘        │
│                                             │                       │
│          ┌──────────────────────────────────┤                       │
│          │                                  │                       │
│  ├───────▼──────┐                 ┌─────────▼──────────┐           │
│  │  PostgreSQL  │                 │  Multi-Provider LLMs│           │
│  │  (SQLAlchemy)│                 │  Anthropic, OpenAI │           │
│  │  Alembic     │                 │  Google, xAI, etc. │           │
│  └──────────────┘                 └────────────────────┘           │
│                                                                     │
│  ┌──────────────┐    ┌─────────────────┐                           │
│  │ File Storage │    │  Webhook Target │                           │
│  │ (local disk) │    │  (configurable) │                           │
│  └──────────────┘    └─────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Document Lifecycle Pipeline

This is the core concept of AuctoriaAI. Every document follows a strict state machine with automated and human-in-the-loop steps.

### State Machine

```
                    ┌─────────────────────────────────────────────────┐
                    │                                                 │
          Upload    │   Extract      Generate     QA +      Govern-  │  Human
 CREATE ──► DRAFT ──┼──► Facts  ──►  Draft   ──► Claims ──► ance ───┼──► Review
            │       │   (LLM)       (LLM)        Check      Gate     │
            │       │                                                 │
            │       └─────────────────────────────────────────────────┘
            │
            ▼
       VALIDATING
            │
      ┌─────┴────────────────┐
      │                      │
      ▼                      ▼
  HUMAN_REVIEW            BLOCKED
      │                      │
   ┌──┴──┐                   │
   │     │                   ▼
   ▼     ▼               (→ DRAFT to retry)
APPROVED BLOCKED
```

### Valid State Transitions

| From          | To            | Trigger                                      |
|---------------|---------------|----------------------------------------------|
| DRAFT         | VALIDATING    | QA iteration starts                          |
| VALIDATING    | PASSED        | QA score ≥ threshold AND claims valid        |
| VALIDATING    | HUMAN_REVIEW  | Governance gate passes                       |
| VALIDATING    | BLOCKED       | QA or claim validation fails                 |
| HUMAN_REVIEW  | APPROVED      | Reviewer approves                            |
| HUMAN_REVIEW  | BLOCKED       | Reviewer rejects                             |
| PASSED        | APPROVED      | Reviewer approves (fast-track)               |
| BLOCKED       | DRAFT         | Admin unblocks to retry                      |

### Pipeline Step Details

| Step | Epic   | Service                    | What Happens                                                                 |
|------|--------|----------------------------|------------------------------------------------------------------------------|
| 1    | EPIC 1 | `document_service`         | Document record created in DB (DRAFT state)                                  |
| 2    | EPIC 2 | `upload_service`           | File (PDF/DOCX/TXT) uploaded, SHA-256 hashed, stored to disk                 |
| 3    | EPIC 2 | `extraction_service`       | Claude LLM reads the document and extracts a structured fact sheet (JSON)    |
| 4    | EPIC 2 | `extraction_service`       | Claim registry seeded/refreshed with approved INTEGRATION/COMPLIANCE/PERF    |
| 5    | EPIC 3 | `draft_generation_service` | Claude generates a markdown whitepaper from fact sheet OR user prompt        |
| 6    | EPIC 4 | `qa_iteration_service`     | Claude evaluates draft with 3-category rubric; iteratively improves up to N times |
| 7    | EPIC 5 | `claim_validation_service` | Regex extracts claims from draft; each validated against claim registry      |
| 8    | EPIC 6 | `governance_service`       | Combines QA score + claim result → HUMAN_REVIEW or BLOCKED                  |
| 9    | EPIC 7 | `review_service`           | Human reviewer sees full context, approves or rejects; webhook fires         |

---

## 4. Technology Stack

### Backend
| Component       | Technology                          |
|-----------------|-------------------------------------|
| Framework       | FastAPI (ASGI, async Python)        |
| ORM             | SQLAlchemy (sync sessions)          |
| Migrations      | Alembic                             |
| Database        | PostgreSQL                          |
| LLM Providers   | Anthropic, OpenAI, Google, xAI, Perplexity |
| LLM SDKs        | anthropic, openai                   |
| PDF export      | ReportLab                           |
| DOCX export     | python-docx                         |
| Retry logic     | Tenacity (exponential backoff)      |
| File hashing    | hashlib (SHA-256)                   |

### Frontend
| Component       | Technology                          |
|-----------------|-------------------------------------|
| Framework       | React 19 (TypeScript)               |
| Build           | Vite                                |
| Routing         | React Router v6                     |
| Server state    | TanStack React Query                |
| HTTP client     | Axios                               |
| Forms           | React Hook Form + Zod               |
| UI primitives   | Radix UI                            |
| Styling         | TailwindCSS                         |
| Charts          | Recharts                            |
| Icons           | Lucide React                        |

### AI Models & Multi-Provider Support

AuctoriaAI supports multiple LLM providers through a unified adapter layer:

| Provider    | Models                          | Integration                              |
|-------------|---------------------------------|------------------------------------------|
| Anthropic   | claude-opus-4-6, claude-sonnet-4-6, etc. | Native Anthropic SDK                     |
| OpenAI      | gpt-4o, gpt-4, o1, o3, etc.     | OpenAI SDK                               |
| Google      | gemini-*, gemini-pro, etc.      | OpenAI-compatible endpoint               |
| xAI         | grok-*, etc.                    | OpenAI-compatible endpoint               |
| Perplexity  | sonar-*, etc.                   | OpenAI-compatible endpoint               |

**Default Configuration:**

| Role              | Model              | Usage                                         |
|-------------------|--------------------|-----------------------------------------------|
| Draft Generation  | claude-opus-4-6    | Fact-grounded whitepaper generation           |
| QA Evaluation     | claude-sonnet-4-6  | Rubric-based evaluation and iterative feedback|
| Fact Extraction   | claude-opus-4-6    | Structured JSON fact extraction from uploads  |

All models are configurable at runtime via Admin Settings. The system automatically detects the provider from the model name prefix and routes requests to the appropriate SDK.

---

## 5. Project Structure

```
AuctoriaAI/
│
├── app/                                  # Backend application root
│   ├── main.py                           # FastAPI app init, CORS, router registration
│   ├── config.py                         # All system defaults and env loading
│   ├── database.py                       # SQLAlchemy engine, session factory, Base
│   │
│   ├── models/
│   │   └── models.py                     # All ORM models (Document, DraftVersion, etc.)
│   │
│   ├── schemas/
│   │   └── schemas.py                    # All Pydantic request/response DTOs
│   │
│   ├── api/
│   │   ├── routes.py                     # All main API endpoints (documents, drafts, review)
│   │   └── admin_routes.py               # Admin endpoints (settings, webhook test)
│   │
│   ├── services/
│   │   ├── document_service.py           # Document CRUD, state machine, draft versioning
│   │   ├── upload_service.py             # File upload, validation, hashing, storage
│   │   ├── extraction_service.py         # LLM fact extraction, registry management
│   │   ├── draft_generation_service.py   # LLM draft generation (fact-grounded + prompt-first)
│   │   ├── qa_iteration_service.py       # Rubric evaluation + iterative QA loop
│   │   ├── claim_validation_service.py   # Regex claim extraction + registry validation
│   │   ├── governance_service.py         # Governance gate (QA score + claims → status)
│   │   ├── review_service.py             # Human review, approval, rejection, webhook
│   │   ├── download_service.py           # PDF and DOCX export from markdown
│   │   ├── notification_service.py       # Webhook POST notifications
│   │   ├── settings_service.py           # Admin settings with in-memory cache
│   │   ├── audit_service.py              # Read-only audit log access
│   │   ├── claim_service.py              # Claim registry CRUD
│   │   ├── llm_adapter.py                # Multi-provider LLM adapter (routes to correct SDK)
│   │   └── exceptions.py                 # Custom exception classes
│   │
│   └── tests/                            # Pytest test suite (one file per epic)
│       ├── test_epic2_upload.py
│       ├── test_epic2_extraction.py
│       ├── test_epic2_claims.py
│       ├── test_epic3_generation.py
│       ├── test_epic4_qa_iteration.py
│       ├── test_epic5_claim_validation.py
│       ├── test_epic6_governance.py
│       ├── test_epic7_review.py
│       ├── test_system_settings.py
│       └── test_state_machine.py
│
├── frontend/                             # React TypeScript frontend
│   ├── src/
│   │   ├── App.tsx                       # App shell, routing
│   │   ├── main.tsx                      # Vite entry point
│   │   ├── pages/                        # Full page components
│   │   │   ├── DocumentList.tsx          # Document list with filters
│   │   │   ├── DocumentDetail.tsx        # Document view + pipeline actions
│   │   │   ├── NewDocument.tsx           # Create or prompt-first generation
│   │   │   ├── ReviewQueue.tsx           # Paginated review queue
│   │   │   ├── ReviewDetail.tsx          # Full context review page
│   │   │   └── AdminDashboard.tsx        # Settings + claim registry management
│   │   ├── components/                   # Reusable UI components
│   │   ├── services/                     # API client functions (Axios)
│   │   ├── hooks/                        # Custom React hooks
│   │   ├── types/                        # TypeScript interfaces and types
│   │   └── providers/                    # React Query and toast providers
│   └── package.json
│
├── alembic/                              # Database migration management
│   ├── versions/                         # 14 migration files
│   └── alembic.ini
│
├── storage/                              # Uploaded files (gitignored in production)
├── requirements.txt                      # Python dependencies
├── .env.example                          # Environment variable template
└── pytest.ini                            # Pytest configuration
```

---

## 6. Database Schema

### Document
The central entity. All other entities reference a document.

| Column              | Type         | Description                                              |
|---------------------|--------------|----------------------------------------------------------|
| `id`                | UUID (PK)    | Primary key                                              |
| `title`             | String       | Document title                                           |
| `status`            | Enum         | DRAFT, VALIDATING, PASSED, HUMAN_REVIEW, BLOCKED, APPROVED |
| `classification`    | Enum         | INTERNAL, CONFIDENTIAL, PUBLIC                           |
| `file_path`         | String       | Path to uploaded file on disk                            |
| `file_hash`         | String       | SHA-256 hash for duplicate detection                     |
| `file_size`         | Integer      | File size in bytes                                       |
| `mime_type`         | String       | Detected MIME type                                       |
| `reviewed_by`       | String       | Reviewer identifier                                      |
| `reviewed_at`       | DateTime     | When the review decision was made                        |
| `review_notes`      | Text         | Reviewer comments                                        |
| `force_approved`    | Boolean      | Admin override flag                                      |
| `validation_report` | JSONB        | Full claim validation results                            |
| `created_at`        | DateTime     | Creation timestamp                                       |
| `updated_at`        | DateTime     | Last update timestamp                                    |

### DraftVersion
Each generation attempt creates an immutable draft version.

| Column               | Type      | Description                                              |
|----------------------|-----------|----------------------------------------------------------|
| `id`                 | UUID (PK) | Primary key                                              |
| `document_id`        | UUID (FK) | Linked document (nullable for standalone drafts)         |
| `iteration_number`   | Integer   | Auto-incremented per document                            |
| `content_markdown`   | Text      | Full draft text in markdown                              |
| `score`              | Float     | Composite QA score (0–10, nullable before evaluation)    |
| `feedback_text`      | Text      | LLM rubric feedback narrative                            |
| `tone`               | String    | "formal", "conversational", or "technical"               |
| `user_prompt`        | Text      | Original generation prompt                               |
| `source_document_id` | UUID (FK) | Optional context document reference                      |
| `created_at`         | DateTime  | Creation timestamp                                       |

### FactSheet
Structured facts extracted by LLM from an uploaded document.

| Column           | Type      | Description                                        |
|------------------|-----------|----------------------------------------------------|
| `id`             | UUID (PK) | Primary key                                        |
| `document_id`    | UUID (FK) | Linked document                                    |
| `structured_data`| JSONB     | Extracted facts (features, integrations, compliance, performance, limitations) |
| `created_at`     | DateTime  | Extraction timestamp                               |

### ClaimRegistry
The approved claim database. Drafts are validated against this registry.

| Column        | Type      | Description                                          |
|---------------|-----------|------------------------------------------------------|
| `id`          | UUID (PK) | Primary key                                          |
| `claim_text`  | Text      | The approved claim string                            |
| `claim_type`  | Enum      | INTEGRATION, COMPLIANCE, or PERFORMANCE              |
| `expiry_date` | Date      | Optional expiry (soft warning if past)               |
| `approved_by` | String    | Who approved this claim                              |
| `approved_at` | DateTime  | When the claim was approved                          |
| `created_at`  | DateTime  | Record creation timestamp                            |
| `updated_at`  | DateTime  | Last update timestamp                                |

### AuditLog
Immutable log of all significant actions per document.

| Column        | Type      | Description                                          |
|---------------|-----------|------------------------------------------------------|
| `id`          | UUID (PK) | Primary key                                          |
| `document_id` | UUID (FK) | Linked document                                      |
| `action`      | Text      | Human-readable action description                    |
| `timestamp`   | DateTime  | When the action occurred                             |

### SystemSettings
Single-row admin-configurable system parameters.

| Column                      | Type     | Default              | Description                                  |
|-----------------------------|----------|----------------------|----------------------------------------------|
| `registry_staleness_hours`  | Integer  | 24                   | Max age of claim registry before blocking    |
| `llm_model_name`            | String   | claude-opus-4-6      | Model for draft generation                   |
| `qa_llm_model`              | String   | claude-sonnet-4-6    | Model for QA evaluation                      |
| `max_draft_length`          | Integer  | 50000                | Maximum draft character length               |
| `qa_passing_threshold`      | Float    | 9.0                  | Minimum QA score to proceed                  |
| `governance_score_threshold`| Float    | 9.0                  | Minimum governance score to pass gate        |
| `max_qa_iterations`         | Integer  | 3                    | Max LLM QA/improvement cycles                |
| `llm_timeout_seconds`       | Integer  | 120                  | LLM API call timeout                         |
| `notification_webhook_url`  | String   | ""                   | Webhook URL for approval/rejection events    |
| `anthropic_api_key`         | String   | NULL                 | Anthropic API key (falls back to env var)    |
| `openai_api_key`            | String   | NULL                 | OpenAI API key                               |
| `google_api_key`            | String   | NULL                 | Google AI API key                            |
| `perplexity_api_key`        | String   | NULL                 | Perplexity API key                           |
| `xai_api_key`               | String   | NULL                 | xAI API key                                  |
| `updated_by`                | String   | —                    | Who last changed settings                    |
| `updated_at`                | DateTime | —                    | When settings were last changed              |

---

## 7. API Reference

All endpoints are prefixed with `/api/v1/`.

### Documents
| Method | Endpoint                                    | Description                                         |
|--------|---------------------------------------------|-----------------------------------------------------|
| POST   | `/documents`                                | Create a new document                               |
| GET    | `/documents`                                | List documents (paginated, filter by status)        |
| GET    | `/documents/{id}`                           | Get document details                                |
| GET    | `/documents/{id}/status`                    | Lightweight status poll for pipeline progress       |
| POST   | `/documents/{id}/transition`                | Manual state transition                             |

### File Upload (EPIC 2)
| Method | Endpoint                                    | Description                                         |
|--------|---------------------------------------------|-----------------------------------------------------|
| POST   | `/documents/{id}/upload`                    | Upload PDF/DOCX/TXT with classification level       |

### Fact Sheets (EPIC 2)
| Method | Endpoint                                    | Description                                         |
|--------|---------------------------------------------|-----------------------------------------------------|
| POST   | `/documents/{id}/extract-factsheet`         | LLM-powered structured fact extraction              |
| POST   | `/documents/{id}/fact-sheets`               | Manual fact sheet creation                          |
| GET    | `/documents/{id}/fact-sheets`               | List fact sheets for document                       |
| GET    | `/documents/{id}/fact-sheets/{sheet_id}`    | Get single fact sheet                               |

### Claim Registry (EPIC 2)
| Method | Endpoint                                    | Description                                         |
|--------|---------------------------------------------|-----------------------------------------------------|
| POST   | `/registry/sync`                            | Initialize or refresh the claim registry            |
| POST   | `/claims`                                   | Create a new approved claim                         |
| GET    | `/claims`                                   | List all claims (with expiry metadata)              |
| GET    | `/claims/{claim_id}`                        | Get single claim                                    |
| POST   | `/claims/validate`                          | Validate a set of claim IDs against registry        |

### Draft Generation (EPIC 3)
| Method | Endpoint                                    | Description                                         |
|--------|---------------------------------------------|-----------------------------------------------------|
| POST   | `/documents/{id}/generate-draft`            | Fact-grounded draft (requires fact sheet)           |
| POST   | `/drafts/generate`                          | Prompt-first standalone draft (no fact sheet needed)|
| GET    | `/documents/{id}/drafts`                    | List all draft versions for document                |
| GET    | `/documents/{id}/drafts/{draft_id}`         | Get a specific draft version                        |

### QA Iteration (EPIC 4)
| Method | Endpoint                                    | Description                                         |
|--------|---------------------------------------------|-----------------------------------------------------|
| POST   | `/documents/{id}/qa-iterate`                | Evaluate draft with rubric; iterate to improve      |

### Claim Validation (EPIC 5)
| Method | Endpoint                                    | Description                                         |
|--------|---------------------------------------------|-----------------------------------------------------|
| POST   | `/documents/{id}/validate-claims`           | Extract claims from draft and validate against registry |

### Governance Gate (EPIC 6)
| Method | Endpoint                                    | Description                                         |
|--------|---------------------------------------------|-----------------------------------------------------|
| POST   | `/documents/{id}/governance-check`          | Combined governance check → HUMAN_REVIEW or BLOCKED |

### Human Review (EPIC 7)
| Method | Endpoint                                    | Description                                         |
|--------|---------------------------------------------|-----------------------------------------------------|
| GET    | `/documents/pending-review`                 | Paginated queue (oldest-first)                      |
| GET    | `/documents/{id}/review-details`            | Full review context (draft, validation, history)    |
| POST   | `/documents/{id}/approve`                   | Approve (normal or force-approve with reason)       |
| POST   | `/documents/{id}/reject`                    | Reject with reason                                  |

### Exports & Audit
| Method | Endpoint                                    | Description                                         |
|--------|---------------------------------------------|-----------------------------------------------------|
| GET    | `/documents/{id}/audit-logs`                | Get full audit trail                                |
| GET    | `/drafts/{draft_id}/download/pdf`           | Stream draft as formatted PDF                       |
| GET    | `/drafts/{draft_id}/download/docx`          | Stream draft as formatted DOCX                      |

### Admin Settings
| Method | Endpoint                                    | Description                                         |
|--------|---------------------------------------------|-----------------------------------------------------|
| GET    | `/admin/settings`                           | Get current system settings                         |
| PUT    | `/admin/settings`                           | Update settings (rate-limited: 5/hour)              |
| POST   | `/admin/settings/test-webhook`              | Test webhook configuration                          |

### Health
| Method | Endpoint   | Description                 |
|--------|------------|-----------------------------|
| GET    | `/health`  | Service health check        |

---

## 8. Services & Business Logic

### `document_service.py`
- CRUD for documents with UUID primary keys
- **State machine enforcement**: Invalid transitions raise `InvalidTransitionError`
- **Draft versioning**: `iteration_number` auto-increments per document using `SELECT FOR UPDATE` to prevent race conditions
- Writes an `AuditLog` entry on every state change

### `upload_service.py`
- Accepts multipart form uploads
- Validates by file extension AND MIME type (PDF, DOCX, TXT only)
- Enforces configurable file size limit (default 50 MB)
- Computes SHA-256 hash; rejects exact duplicates
- Stores file at `{storage_path}/{document_id}/{filename}`

### `extraction_service.py`
- **Registry freshness gate**: Before any extraction, checks registry age
  - Empty registry → `RegistryNotInitializedError` (bypassed in `local`/`development` ENV)
  - Stale registry → `RegistryStaleError`
- Calls Claude API with a structured extraction prompt
- Validates response as `FactSheetData` JSON schema
- `sync_registry()` seeds 12 default claims (integrations, compliance, performance)

### `draft_generation_service.py`
Two independent generation paths:

**Path A — Fact-Grounded (Document-First)**
1. Requires a FactSheet on the document
2. Builds a structured prompt from extracted features, integrations, and compliance data
3. Calls Claude claude-opus-4-6 with the fact context
4. Saves result as a new `DraftVersion`

**Path B — Prompt-First (Standalone)**
1. User prompt is the primary input
2. Document context is optional; never requires FactSheet
3. Bypasses registry checks entirely
4. Same draft versioning and output format as Path A

Both paths support tone selection: `formal`, `conversational`, `technical`.

### `qa_iteration_service.py`
**Rubric categories** (each scored 0–10):
- Factual Correctness
- Technical Depth
- Clarity & Structure

**Composite Score** = average of three categories

**Iterative loop:**
```
evaluate draft → composite score
  if score ≥ threshold → PASS
  elif iterations < max_iterations → improve draft → evaluate again
  else → FAIL (use best score achieved)
```
- Each iteration creates a new `DraftVersion` with its score and feedback
- Atomic database transactions; full rollback on failure
- Each iteration writes an audit log entry

### `claim_validation_service.py`
**Claim extraction via regex patterns:**

| Claim Type    | Pattern Examples                                          |
|---------------|-----------------------------------------------------------|
| INTEGRATION   | "integrates with X", "supports X"                         |
| COMPLIANCE    | "compliant with X", "meets X standard"                    |
| PERFORMANCE   | "achieves X% uptime", "X ms latency"                      |
| SUPERLATIVE   | "first", "only", "best", "industry-leading"               |

**Validation logic:**
- For each extracted claim, look up in `ClaimRegistry`
- Not found → HARD FAIL (blocks document)
- Found but expired → SOFT WARNING (logged, doesn't block)
- Superlative without nearby performance metric → HARD FAIL
- Saves full `validation_report` JSONB to the document

### `governance_service.py`
Combines QA and claim results into a binary governance decision:

```
if qa_score >= threshold AND claims_valid:
    transition → HUMAN_REVIEW (PASSED)
else:
    transition → BLOCKED (FAILED)
```
- Idempotent: safe to call multiple times on the same document
- Reads latest draft score from the most recent `DraftVersion`

### `review_service.py`
- Returns pending documents in FIFO order (oldest `updated_at` first)
- `get_review_details()` assembles: draft history, validation report, fact sheet, recent audit logs, days-in-review count
- **Normal approval**: Document must be in `HUMAN_REVIEW`
- **Force-approve**: Admin override from ANY status; requires `override_reason`
- Rejection always records reason and optional suggested action
- Calls `notification_service` after every decision (best-effort, never blocks)

### `settings_service.py`
- Auto-seeds `SystemSettings` row on first boot from `config.py` defaults
- 60-second in-memory cache (TTL-based)
- Cache invalidated immediately on write
- Rate-limited: 5 updates per rolling hour per admin
- **Production note**: Multi-worker deployments need Redis or shared cache

### `llm_adapter.py`
- **Multi-provider routing**: Automatically detects provider from model name prefix (e.g., `claude-*` → Anthropic, `gpt-*` → OpenAI, `gemini-*` → Google)
- **Unified interface**: Single `call_llm()` function works with all providers
- **Provider SDKs**: Uses native Anthropic SDK for Claude; OpenAI SDK (or OpenAI-compatible endpoints) for OpenAI, Google, xAI, and Perplexity
- **API key management**: Retrieves keys from `SystemSettings` database; falls back to `ANTHROPIC_API_KEY` environment variable for Anthropic
- **Configurable base URLs**: Each provider has a configured API endpoint for OpenAI-compatible routing

---

## 9. Governance Gates & Safety Mechanisms

AuctoriaAI has five sequential safety gates. A document must pass ALL of them to reach APPROVED.

### Gate 1 — Registry Freshness Gate
- **Where**: `extraction_service.py` before every fact extraction
- **Checks**: Is the claim registry initialized and fresh?
- **Fail behavior**: `RegistryNotInitializedError` or `RegistryStaleError` — pipeline stops
- **Bypass**: In `local` and `development` environments only

### Gate 2 — File Validation Gate
- **Where**: `upload_service.py`
- **Checks**: File type (PDF/DOCX/TXT), size limit (50 MB), SHA-256 duplicate detection
- **Fail behavior**: HTTP 400 with specific error; file rejected before storage

### Gate 3 — QA Scoring Gate
- **Where**: `qa_iteration_service.py`
- **Checks**: Composite rubric score across Factual Correctness, Technical Depth, Clarity
- **Fail behavior**: After max iterations, document remains in low-score state
- **Configurable**: `qa_passing_threshold` (default 9.0/10), `max_qa_iterations` (default 3)

### Gate 4 — Claim Validation Gate
- **Where**: `claim_validation_service.py`
- **Checks**: Every claim in the draft exists in the approved claim registry
- **Fail behavior**: `blocked_claims` count > 0 → document status → BLOCKED
- **Special rule**: Superlatives require adjacent performance metric claims

### Gate 5 — Governance Gate
- **Where**: `governance_service.py`
- **Checks**: BOTH Gate 3 AND Gate 4 must have passed
- **Fail behavior**: Either failing → BLOCKED
- **Pass behavior**: → HUMAN_REVIEW (human final decision required)

### Admin Override
- Any BLOCKED document can be force-approved by an admin
- Force-approve requires an `override_reason` text
- Force-approve is logged in audit trail and flagged on the document (`force_approved = true`)
- Admin settings are rate-limited (5 updates/hour) to prevent misconfiguration

---

## 10. Configuration & Environment

### Environment Variables

Copy `.env.example` to `.env` and configure:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/veritas_ai
ENV=local          # local | development | staging | production
```

The `ENV` value controls:
- `local` / `development`: Registry freshness gates are bypassed (for development ease)
- `staging` / `production`: Full governance enforcement (all gates active)

### System Defaults (`config.py`)

```python
cors_origins              = ["http://localhost:5173", "http://127.0.0.1:5173"]
storage_path              = "/app/storage/documents"
max_file_size_bytes       = 52_428_800     # 50 MB
registry_staleness_hours  = 24             # hours
llm_model_name            = "claude-opus-4-6"
qa_llm_model              = "claude-sonnet-4-6"
max_draft_length          = 50_000         # characters
qa_passing_threshold      = 9.0
max_qa_iterations         = 3
governance_score_threshold = 9.0
llm_timeout_seconds       = 120
notification_webhook_url  = ""             # empty = disabled
```

All defaults are overridable at runtime via the Admin Settings API without a server restart.

### LLM API Keys

#### Environment Variables (Legacy)
The system supports environment variable fallback for Anthropic:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

#### Database Configuration (Recommended)
API keys for all providers can be configured at runtime via Admin Settings (no restart required):

- **Anthropic**: Falls back to `ANTHROPIC_API_KEY` environment variable if not set in DB
- **OpenAI**: Must be configured in Admin Settings
- **Google AI**: Must be configured in Admin Settings
- **Perplexity**: Must be configured in Admin Settings
- **xAI**: Must be configured in Admin Settings

To configure API keys:
1. Navigate to Admin → System Settings in the frontend
2. Enter API keys in the "API Keys" section
3. Select desired models for draft generation and QA evaluation
4. Save settings (no server restart required)

---

## 11. Frontend Architecture

### Page Map

| Route                  | Page               | Purpose                                           |
|------------------------|--------------------|---------------------------------------------------|
| `/documents`           | DocumentList       | Browse all documents, filter by status            |
| `/documents/new`       | NewDocument        | Create document or generate draft from prompt     |
| `/documents/:id`       | DocumentDetail     | View doc, upload file, run pipeline steps         |
| `/review`              | ReviewQueue        | Paginated queue of HUMAN_REVIEW documents         |
| `/review/:id`          | ReviewDetail       | Full context: draft, validation, history, decision|
| `/admin`               | AdminDashboard     | System settings + claim registry management       |

### Data Fetching Pattern

All server state is managed via **TanStack React Query**:
- Automatic background refetching on window focus
- Optimistic updates on mutations
- Loading and error boundary states built-in
- API polling for document status during pipeline execution

### Component Architecture

```
providers/
  ├── QueryProvider.tsx       # React Query client configuration
  └── ToastProvider.tsx       # Toast notification context

pages/
  ├── DocumentList.tsx        # TanStack Query: useDocuments()
  ├── DocumentDetail.tsx      # TanStack Query: useDocument(), useDrafts()
  ├── ReviewDetail.tsx        # TanStack Query: useReviewDetails()
  └── AdminDashboard.tsx      # TanStack Query: useSettings(), useClaims()

services/
  ├── documentApi.ts          # Axios calls → /api/v1/documents
  ├── draftApi.ts             # Axios calls → /api/v1/drafts
  ├── claimApi.ts             # Axios calls → /api/v1/claims
  └── adminApi.ts             # Axios calls → /api/v1/admin
```

---

## 12. Running Locally

### Prerequisites
- Python 3.10+
- PostgreSQL 14+
- Node.js 18+
- At least one LLM provider API key (Anthropic, OpenAI, Google AI, xAI, or Perplexity)

### Backend Setup

```bash
# Clone and enter project directory
cd AuctoriaAI

# Create virtual environment
python -m venv venv
source venv/bin/activate       # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env: set DATABASE_URL and ENV=local

# Export LLM API key (for Anthropic - optional if configured in Admin Settings)
export ANTHROPIC_API_KEY=sk-ant-...
# OR configure API keys via Admin Settings after startup

# Run database migrations
python -m alembic upgrade head

# Start the backend server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend API will be available at: `http://localhost:8000`
Interactive docs (Swagger UI): `http://localhost:8000/docs`

### Frontend Setup

```bash
# In a separate terminal
cd AuctoriaAI/frontend

# Install Node dependencies
npm install

# Start development server
npm run dev
```

Frontend will be available at: `http://localhost:5173`

### Initialize the Claim Registry

After startup, seed the default claim registry:

```bash
curl -X POST http://localhost:8000/api/v1/registry/sync
```

---

## 13. Database Migrations

Managed with Alembic. Migration files are in `alembic/versions/`.

```bash
# Apply all migrations (upgrade to latest)
python -m alembic upgrade head

# Check current migration state
python -m alembic current

# Generate a new migration from model changes
alembic revision --autogenerate -m "describe_your_change"

# Roll back one migration
python -m alembic downgrade -1

# Roll back all migrations
python -m alembic downgrade base
```

### Migration History Summary
14 migrations covering:
1. Initial schema (Document, DraftVersion, FactSheet)
2. UUID type fixes
3. Upload metadata fields (file_hash, file_size, mime_type, classification)
4. Claim registry (ClaimRegistry model)
5. Draft feedback text
6. Validation report JSONB on Document
7. Review metadata (reviewed_by, reviewed_at, review_notes)
8. Tone field on DraftVersion
9. SystemSettings table
10. SystemSettings ID type fix
11. Prompt-first draft support (source_document_id, user_prompt)
12. Pipeline progress tracking columns
13. LLM timeout configuration
14. Multi-provider API key support (anthropic, openai, google, perplexity, xai)

---

## 14. Testing

### Backend (pytest)

```bash
# Run all tests
pytest

# Run specific epic tests
pytest app/tests/test_epic3_generation.py -v

# Run with coverage report
python -m pytest --cov=app --cov-report=html

# Run a single test
pytest app/tests/test_epic4_qa_iteration.py::test_qa_passes_on_high_score -v
```

### Test Coverage by Epic

| File                          | What It Tests                                             |
|-------------------------------|-----------------------------------------------------------|
| `test_epic2_upload.py`        | File type rejection, size limits, duplicate detection     |
| `test_epic2_extraction.py`    | LLM fact extraction, registry freshness gate              |
| `test_epic2_claims.py`        | Claim CRUD, expiry handling                               |
| `test_epic3_generation.py`    | Fact-grounded and prompt-first draft generation           |
| `test_epic4_qa_iteration.py`  | Rubric scoring, iteration loop, pass/fail thresholds      |
| `test_epic5_claim_validation.py` | Regex extraction, registry matching, superlative rules |
| `test_epic6_governance.py`    | Combined governance gate logic                            |
| `test_epic7_review.py`        | Approve, force-approve, reject, webhook trigger           |
| `test_system_settings.py`     | Settings CRUD, cache, rate limiting                       |
| `test_state_machine.py`       | All valid/invalid state transitions                       |

### Frontend Tests

```bash
cd frontend

# Unit tests (Vitest)
npm run test

# E2E tests (Playwright — desktop)
npm run test:e2e

# E2E tests (Playwright — mobile)
npm run test:e2e:mobile
```

Frontend tests use **Mock Service Worker (MSW)** to intercept API calls without a running backend.

---

## 15. Deployment Considerations

### Production Environment

```env
DATABASE_URL=postgresql://user:password@db-host:5432/veritas_ai
ENV=production
# Optional: Legacy environment variable for Anthropic (can be configured in Admin Settings instead)
ANTHROPIC_API_KEY=sk-ant-...
```

**Recommended**: Configure all LLM provider API keys via Admin Settings UI rather than environment variables for easier key rotation and multi-provider management.

### Important Production Notes

**1. Multi-Worker Settings Cache**
`settings_service.py` uses an in-memory dict cache (60-second TTL). In multi-worker deployments (e.g., Gunicorn with 4 workers), each worker has its own cache. This is safe but may cause brief inconsistency after settings updates. For strict consistency, replace with Redis cache.

**2. File Storage**
Currently uses local disk (`storage/`). For production with multiple replicas, mount a shared volume or migrate to object storage (S3-compatible) by modifying `upload_service.py` and `download_service.py`.

**3. Authentication**
The current admin guard (`_require_admin()`) is a no-op placeholder. Wire in your JWT/session auth before exposing admin routes publicly.

**4. Webhook Reliability**
Webhook notifications (`notification_service.py`) are synchronous and best-effort (failures are logged but ignored). For guaranteed delivery, move to a message queue (Celery + Redis, or SQS).

**5. Database Locking**
Draft iteration uses `SELECT FOR UPDATE` to prevent concurrent creation races. This requires PostgreSQL (not SQLite). The application is designed for PostgreSQL in all environments.

### Recommended Production Stack
```
Load Balancer
    ↓
Uvicorn / Gunicorn workers (2-4 per CPU)
    ↓
PostgreSQL (RDS or managed)
    ↓
Shared volume or S3 for file storage
    ↓
Redis (for settings cache in multi-worker)
    ↓
LLM Providers (Anthropic, OpenAI, Google, xAI, Perplexity)
```

---

## 16. Key Design Decisions

### Why Multi-Provider LLM Support?
AuctoriaAI supports multiple LLM providers (Anthropic, OpenAI, Google, Perplexity, xAI) to give organizations flexibility in model selection based on their specific needs, cost considerations, and provider preferences. The system uses a unified adapter layer (`llm_adapter.py`) that automatically routes requests to the appropriate SDK based on model name prefixes.

By default, the system uses separate Claude models (claude-opus-4-6 for generation, claude-sonnet-4-6 for evaluation) to balance quality and cost: the most capable model generates the best output, while the faster/cheaper model handles high-volume iterative scoring without significantly sacrificing evaluation quality. However, any supported model from any provider can be configured for either role via Admin Settings.

### Why Regex-Based Claim Extraction (Not LLM)?
Claim extraction uses regex patterns rather than an LLM call. This keeps validation deterministic, fast, and auditable. LLM-based extraction would add latency, cost, and non-determinism to what needs to be a reliable gate.

### Why a Single-Row SystemSettings Table?
All configurable thresholds live in one DB row, editable at runtime via API. This avoids restart-required config changes in production, enables audit trails on setting changes, and allows threshold tuning without code deployments.

### Why BLOCKED → DRAFT (Not BLOCKED → HUMAN_REVIEW)?
BLOCKED documents return to DRAFT so the author can fix issues and re-run the full pipeline. Sending BLOCKED documents directly to review would push incomplete work to reviewers, undermining the purpose of the automated gates.

### Why Fact-Grounded and Prompt-First Are Separate Paths?
Fact-grounded generation requires a complete source document, fact extraction, and registry validation. Prompt-first is for quick ideation where no source document exists yet. Forcing both through the same path would either restrict prompt-first or weaken fact-grounded governance. Keeping them separate preserves the strict governance guarantees where they matter.

### Why Audit Logs Are Immutable?
`AuditLog` has no update or delete operation. This creates a tamper-evident record of the document's history — critical for compliance-regulated environments where proving review occurred is as important as the review itself.

---

## Summary

AuctoriaAI is best understood as an **LLM governance pipeline** wrapped in a full-stack application. Its core value is not document generation (Claude can do that alone) but the **automated and human verification layer** that sits between raw LLM output and approved organizational communication. Every approval in AuctoriaAI is backed by a QA score, a claim validation report, and a human reviewer decision — all stored in an immutable audit trail.
