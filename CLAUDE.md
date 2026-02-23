# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VeritasAI is an AI-powered document governance platform that enforces quality, accuracy, and compliance for AI-generated documents. It runs documents through a 7-epic pipeline: upload → extract facts → generate draft → QA iterate → validate claims → governance gate → human review.

## Commands

### Backend (Python/FastAPI)

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Run server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Database migrations
python -m alembic upgrade head
alembic revision --autogenerate -m "describe_change"
python -m alembic downgrade -1

# Tests
pytest                                                        # all tests
pytest app/tests/test_epic3_generation.py -v                  # single file
pytest app/tests/test_epic4_qa_iteration.py::test_qa_passes_on_high_score -v  # single test
python -m pytest --cov=app --cov-report=html                  # with coverage

# Initialize claim registry (required before extraction)
curl -X POST http://localhost:8000/api/v1/registry/sync
```

### Frontend (React/TypeScript)

```bash
cd frontend
npm install
npm run dev           # dev server on port 5173
npm run build         # production build
npm run lint          # ESLint
npm run lint:fix
npm run type-check    # TypeScript check
npm run test          # Vitest unit tests
npm run test:watch
npm run test:coverage
npm run test:e2e      # Playwright
npm run test:e2e:headed
```

## Architecture

### Stack
- **Backend**: FastAPI + SQLAlchemy 2.0 + PostgreSQL + Alembic
- **Frontend**: React 19 + TypeScript + Vite + TanStack React Query + TailwindCSS + Radix UI
- **AI**: Anthropic Claude API — `claude-opus-4-6` for draft generation/extraction, `claude-sonnet-4-6` for QA evaluation
- **Exports**: ReportLab (PDF), python-docx (DOCX)

### Environment Variables (`.env`)
```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/veritas_ai
ENV=local   # local | development | staging | production
ANTHROPIC_API_KEY=sk-ant-...
```

`ENV=local` or `ENV=development` bypasses registry freshness gates for easier development. `staging`/`production` enforces full governance.

### Document State Machine

Documents transition through these states, enforced in `document_service.py`:

```
DRAFT → VALIDATING → PASSED → APPROVED
                   ↘ HUMAN_REVIEW → APPROVED
                   ↘ BLOCKED → DRAFT (author retries)
```

Invalid transitions raise `InvalidTransitionError`. Every transition is recorded in the immutable audit log.

### 7-Epic Pipeline (Sequential)

| Epic | Service | What Happens |
|------|---------|--------------|
| 1 | document_service | Document record created (DRAFT state) |
| 2 | upload_service → extraction_service | File uploaded + SHA-256 hashed; LLM extracts fact sheet; claim registry seeded |
| 3 | draft_generation_service | Claude generates markdown draft (fact-grounded or prompt-first path) |
| 4 | qa_iteration_service | Claude evaluates with 3-category rubric; iterates up to `max_qa_iterations` |
| 5 | claim_validation_service | Regex extracts claims; validates against claim registry |
| 6 | governance_service | Combines QA score + claims → HUMAN_REVIEW or BLOCKED |
| 7 | review_service | Human reviewer approves/rejects with full context |

### 5 Sequential Safety Gates

1. **Registry Freshness** (`extraction_service`): Registry must be initialized and ≤24h stale (bypassed locally)
2. **File Validation** (`upload_service`): Type (PDF/DOCX/TXT), size (50MB), SHA-256 duplicate check
3. **QA Scoring** (`qa_iteration_service`): Composite rubric score across Factual Correctness + Technical Depth + Clarity; threshold default 9.0/10
4. **Claim Validation** (`claim_validation_service`): Every claim must exist in registry (regex-based, not LLM — deterministic); superlatives require adjacent performance metrics
5. **Governance Gate** (`governance_service`): Both Gate 3 AND Gate 4 must pass → HUMAN_REVIEW; else → BLOCKED

Admin force-approve overrides BLOCKED from any state with a mandatory reason, logged in audit trail.

### Service Layer (`app/services/`)

Key services and their responsibilities:
- `document_service.py` — Document CRUD, state machine, draft versioning with `SELECT FOR UPDATE` for race safety
- `upload_service.py` — Multipart upload, validation, hashing, storage at `{storage_path}/{document_id}/{filename}`
- `extraction_service.py` — LLM fact extraction, registry freshness gate, default claim seeding
- `draft_generation_service.py` (48KB) — Two separate paths: fact-grounded (requires FactSheet) vs. prompt-first (standalone)
- `qa_iteration_service.py` (57KB) — Rubric evaluation loop, creates new DraftVersion per iteration with score/feedback
- `claim_validation_service.py` — Regex claim extraction (INTEGRATION, COMPLIANCE, PERFORMANCE, SUPERLATIVE types), registry matching
- `governance_service.py` — Combines QA + claim results, idempotent
- `review_service.py` — FIFO review queue, full context assembly, webhook notifications
- `settings_service.py` — Single-row SystemSettings with 60s in-memory cache (TTL), auto-seeded on boot, rate-limited 5 updates/hour

### Runtime-Configurable Settings

All thresholds are tunable via `PUT /api/v1/admin/settings` without restart:
- `qa_passing_threshold` (default 9.0), `max_qa_iterations` (3), `governance_score_threshold` (9.0)
- `max_draft_length` (50,000 chars), `llm_timeout_seconds` (120)
- `llm_model_name`, `qa_llm_model`, `notification_webhook_url`

**Multi-worker caveat**: Settings cache is in-memory per worker; inconsistency is possible. Use Redis for strict consistency in production.

### API Structure

All endpoints prefixed with `/api/v1/`. Key groupings:
- `/documents` — CRUD, state transitions, status polling
- `/documents/{id}/upload`, `/extract-factsheet`, `/fact-sheets` — Epic 2
- `/drafts/generate`, `/documents/{id}/generate-draft` — Epic 3 (two paths)
- `/documents/{id}/qa-iterate`, `/validate-claims`, `/governance-check` — Epics 4-6
- `/documents/pending-review`, `/documents/{id}/approve`, `/documents/{id}/reject` — Epic 7
- `/claims`, `/registry/sync` — Claim registry management
- `/admin/settings` — System configuration
- `/drafts/{id}/download/pdf`, `/drafts/{id}/download/docx` — Export

### Frontend Architecture

- **Routing**: React Router v6, pages in `src/pages/`
- **Server state**: TanStack React Query with auto-refetch, polling during pipeline execution
- **API calls**: Axios clients in `src/services/` (documentApi, draftApi, claimApi, adminApi)
- **Forms**: React Hook Form + Zod validation
- **UI**: Radix UI primitives in `src/components/ui/`, Lucide React icons
- **Test mocking**: MSW (Mock Service Worker) with handlers in `src/test/`
- **Deployment**: Vercel with SPA rewrite (`vercel.json`)

### Database Schema

Core tables: `documents`, `draft_versions`, `fact_sheets`, `claim_registry`, `audit_logs`, `system_settings` (single-row).

`audit_logs` is immutable — no update/delete operations anywhere in the codebase.

13 Alembic migrations in `alembic/versions/` — always run `python -m alembic upgrade head` after pulling changes.

### Test Organization

Backend tests in `app/tests/` are organized by epic (`test_epic2_upload.py` through `test_epic7_review.py`), plus `test_state_machine.py` and `test_system_settings.py`. `pytest.ini` sets `testpaths = app/tests`.

Frontend unit tests use Vitest with jsdom. E2E tests use Playwright with desktop and mobile variants.
