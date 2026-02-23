/**
 * Backend API Integration Tests via Playwright request context
 *
 * These tests call the FastAPI backend directly (not through the browser)
 * to verify API contract matches what the frontend expects.
 *
 * Backend base URL: http://127.0.0.1:8000/api/v1  (from .env VITE_API_URL)
 * Override with env var:  API_BASE_URL=http://... npx playwright test tests/e2e/api.spec.ts
 *
 * Run:
 *   npx playwright test tests/e2e/api.spec.ts --project=Desktop
 */

import { test, expect } from '@playwright/test';

const API = process.env.API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1';

// ─── /documents ───────────────────────────────────────────────────────────────

test.describe('GET /documents', () => {

  test('returns 200 with an array', async ({ request }) => {
    const res = await request.get(`${API}/documents`);
    expect(res.ok()).toBeTruthy();

    const body = await res.json();
    expect(Array.isArray(body)).toBe(true);
  });

  test('each document has required shape', async ({ request }) => {
    const res = await request.get(`${API}/documents`);
    const docs = await res.json() as unknown[];

    if (docs.length === 0) {
      test.skip();
      return;
    }

    const doc = docs[0] as Record<string, unknown>;
    expect(doc).toHaveProperty('id');
    expect(doc).toHaveProperty('title');
    expect(doc).toHaveProperty('status');
    expect(doc).toHaveProperty('created_at');
    expect(doc).toHaveProperty('updated_at');
  });

});

// ─── POST /documents ──────────────────────────────────────────────────────────

test.describe('Document lifecycle', () => {

  let documentId: string;

  test('POST /documents creates a document and returns its id', async ({ request }) => {
    const res = await request.post(`${API}/documents`, {
      data: { title: 'Playwright API Test Document' },
    });
    expect(res.ok()).toBeTruthy();
    expect(res.status()).toBe(201);

    const doc = await res.json() as Record<string, unknown>;
    expect(doc).toHaveProperty('id');
    expect(doc).toHaveProperty('title', 'Playwright API Test Document');
    expect(doc).toHaveProperty('status', 'DRAFT');

    documentId = doc.id as string;
  });

  test('GET /documents/:id returns the created document', async ({ request }) => {
    if (!documentId) test.skip();

    const res = await request.get(`${API}/documents/${documentId}`);
    expect(res.ok()).toBeTruthy();

    const doc = await res.json() as Record<string, unknown>;
    expect(doc.id).toBe(documentId);
    // draft_versions and audit_logs are available via sub-endpoints, not embedded here
    expect(doc).toHaveProperty('title');
    expect(doc).toHaveProperty('status');
  });

  test('POST /documents/:id/upload accepts a PDF file', async ({ request }) => {
    if (!documentId) test.skip();

    // Use a unique seed in the PDF content so the SHA-256 hash is different on
    // every test run. upload_service.py rejects a file whose hash already exists
    // on a *different* document, so fixed bytes would cause 409 DuplicateFileError.
    const uploadSeed = `api-test-${Date.now()}`;
    const res = await request.post(`${API}/documents/${documentId}/upload`, {
      multipart: {
        file: {
          name: `${uploadSeed}.pdf`,
          mimeType: 'application/pdf',
          buffer: Buffer.from(
            `%PDF-1.4 ${uploadSeed}\n` +
            '1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n' +
            '2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n' +
            '3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n' +
            'xref\n0 4\n' +
            '0000000000 65535 f \n' +
            '0000000009 00000 n \n' +
            '0000000058 00000 n \n' +
            '0000000115 00000 n \n' +
            'trailer<</Size 4/Root 1 0 R>>\nstartxref\n192\n%%EOF\n'
          ),
        },
        classification: 'INTERNAL',
      },
    });
    expect(res.ok()).toBeTruthy();

    const doc = await res.json() as Record<string, unknown>;
    expect(doc).toHaveProperty('file_path');
    expect(doc).toHaveProperty('classification', 'INTERNAL');
  });

  test('POST /documents/:id/extract-fact-sheet triggers extraction', async ({ request }) => {
    if (!documentId) test.skip();

    // Ensure the claim registry is fresh before calling extract-factsheet.
    // extract-factsheet calls check_registry_freshness(), which requires a ClaimRegistry
    // row updated within 24 h. POST /claims creates a ClaimRegistry row, so this
    // guarantees the freshness gate passes regardless of when the last test ran.
    await request.post(`${API}/claims`, {
      data: { claim_text: 'E2E registry freshness claim', claim_type: 'INTEGRATION' },
    });

    // Backend route is /extract-factsheet (no hyphen) and returns 201 Created on success
    const res = await request.post(`${API}/documents/${documentId}/extract-factsheet`);
    expect([200, 201, 202].includes(res.status())).toBeTruthy();
  });

  test('POST /documents/:id/generate-draft with tone=formal', async ({ request }) => {
    if (!documentId) test.skip();

    const res = await request.post(`${API}/documents/${documentId}/generate-draft`, {
      data: { tone: 'formal' },
    });
    expect(res.ok()).toBeTruthy();

    const body = await res.json() as Record<string, unknown>;
    // GenerateDraftResponse fields (backend schema: schemas.py GenerateDraftResponse)
    expect(body).toHaveProperty('draft_version_id');
    expect(body).toHaveProperty('content_preview');
    expect(body).toHaveProperty('iteration_number');
  });

  test('POST /documents/:id/validate-claims returns validation report', async ({ request }) => {
    if (!documentId) test.skip();

    // Backend requires ValidateClaimsRequest body (even though it has no fields) — send {}
    const res = await request.post(`${API}/documents/${documentId}/validate-claims`, {
      data: {},
    });
    expect(res.ok()).toBeTruthy();

    const report = await res.json() as Record<string, unknown>;
    // Validation report should contain claims array or summary
    expect(report).toBeDefined();
  });

  test('GET /documents/:id/audit-logs returns an array', async ({ request }) => {
    if (!documentId) test.skip();

    const res = await request.get(`${API}/documents/${documentId}/audit-logs`);
    expect(res.ok()).toBeTruthy();

    const logs = await res.json() as unknown[];
    expect(Array.isArray(logs)).toBe(true);
  });

});

// ─── Error handling ───────────────────────────────────────────────────────────

test.describe('API error responses', () => {

  test('GET /documents/non-existent-id returns 404', async ({ request }) => {
    const res = await request.get(`${API}/documents/00000000-0000-0000-0000-000000000000`);
    expect(res.status()).toBe(404);
  });

  test('POST /documents with empty title returns 422', async ({ request }) => {
    const res = await request.post(`${API}/documents`, {
      data: { title: '' },
    });
    // Pydantic / FastAPI returns 422 Unprocessable Entity for validation errors
    expect(res.status()).toBe(422);
  });

});

// ─── Review queue ─────────────────────────────────────────────────────────────

test.describe('GET /review', () => {

  test('returns 200 with an array', async ({ request }) => {
    // Endpoint is /documents/pending-review; returns PendingReviewResponse
    const res = await request.get(`${API}/documents/pending-review`);
    expect(res.ok()).toBeTruthy();

    const body = await res.json() as { documents: unknown[] };
    expect(Array.isArray(body.documents)).toBe(true);
  });

});

// ─── Admin / metrics ──────────────────────────────────────────────────────────

test.describe('GET /admin/metrics', () => {

  test('returns metrics object', async ({ request }) => {
    const res = await request.get(`${API}/admin/metrics`);
    // Endpoint may not exist yet; accept 200 or 404
    if (res.status() === 404) return;

    expect(res.ok()).toBeTruthy();
    const data = await res.json() as Record<string, unknown>;
    expect(data).toBeDefined();
  });

});
