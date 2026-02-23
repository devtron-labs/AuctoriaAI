import { http, HttpResponse } from 'msw';

const BASE = '/api';

const mockDocuments = [
  {
    id: 'doc-1',
    title: 'Test Document One',
    status: 'DRAFT',
    classification: 'INTERNAL',
    created_at: '2025-01-15T10:00:00Z',
    updated_at: '2025-01-15T10:00:00Z',
    file_name: 'test.pdf',
    file_size: 102400,
  },
  {
    id: 'doc-2',
    title: 'Approved Doc',
    status: 'APPROVED',
    classification: 'PUBLIC',
    created_at: '2025-01-10T08:00:00Z',
    updated_at: '2025-01-12T12:00:00Z',
    file_name: 'report.pdf',
    file_size: 204800,
  },
];

export const handlers = [
  // GET /api/documents — paginated list
  http.get(`${BASE}/documents`, ({ request }) => {
    const url = new URL(request.url);
    const page = Number(url.searchParams.get('page') ?? 1);
    const limit = Number(url.searchParams.get('limit') ?? 10);
    const paginated = mockDocuments.slice((page - 1) * limit, page * limit);
    return HttpResponse.json({
      documents: paginated,
      total: mockDocuments.length,
      page,
      limit,
    });
  }),

  // GET /api/documents/:id — single document
  http.get(`${BASE}/documents/:id`, ({ params }) => {
    const doc = mockDocuments.find((d) => d.id === params.id);
    if (!doc) {
      return HttpResponse.json({ detail: 'Document not found' }, { status: 404 });
    }
    return HttpResponse.json(doc);
  }),

  // POST /api/documents — create document
  http.post(`${BASE}/documents`, async ({ request }) => {
    const body = (await request.json()) as { title: string };
    return HttpResponse.json(
      { id: 'new-doc-123', title: body.title, status: 'DRAFT', created_at: new Date().toISOString() },
      { status: 201 }
    );
  }),

  // POST /api/documents/:id/upload — file upload
  http.post(`${BASE}/documents/:id/upload`, () => {
    return HttpResponse.json({ message: 'File uploaded successfully' });
  }),

  // GET /api/documents/pending-review — review queue
  http.get(`${BASE}/documents/pending-review`, () => {
    return HttpResponse.json({
      documents: mockDocuments.filter((d) => d.status === 'HUMAN_REVIEW'),
      total: 0,
    });
  }),

  // GET /api/claims
  http.get(`${BASE}/claims`, () => {
    return HttpResponse.json([]);
  }),

  // Error scenario: /api/documents/invalid — 404
  http.get(`${BASE}/documents/invalid`, () => {
    return HttpResponse.json({ detail: 'Not found' }, { status: 404 });
  }),
];
