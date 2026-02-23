# VeritasAI Frontend

Production-ready React + TypeScript frontend for the VeritasAI document governance platform.

## Tech Stack

| Tool | Version | Purpose |
|---|---|---|
| React | 19 | UI framework |
| TypeScript | 5.9 | Type safety |
| Vite | 7 | Build tool & dev server |
| React Router | 6 | Client-side routing |
| TanStack Query | 5 | Server state & caching |
| Tailwind CSS | 3.4 | Utility-first styling |
| shadcn/ui | — | Accessible component primitives |
| Axios | 1 | HTTP client |
| React Hook Form + Zod | — | Form state & validation |
| Recharts | 3 | Analytics charts |
| Vitest + RTL | 4 | Unit & integration testing |
| MSW | 2 | API mocking in tests |

## Requirements

- **Node.js** ≥ 20.x
- **npm** ≥ 10.x

## Local Development

```bash
# 1. Install dependencies
npm install

# 2. Copy environment config
cp .env.example .env.local

# 3. Set your backend URL in .env.local
echo "VITE_API_URL=http://127.0.0.1:8000/api/v1" > .env.local

# 4. Start dev server
npm run dev
```

The app will be available at http://localhost:5173.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `VITE_API_URL` | Yes | Base URL of the backend API (no trailing slash) |

For production, set this in Vercel project settings (do not commit `.env.production` with real values).

## Build

```bash
# Type-check + build for production
npm run build

# Preview the production build locally
npm run preview
```

Output is written to `dist/`. The build includes:
- esbuild minification
- Source maps
- Code splitting: `vendor`, `charts`, `query` chunks

## Testing

```bash
# Run all tests once
npm test

# Run in watch mode (during development)
npm run test:watch

# Open Vitest UI in browser
npm run test:ui

# Generate coverage report (output: coverage/)
npm run test:coverage
```

### Test structure

```
src/
├── test/
│   ├── setup.ts          # jest-dom + MSW server lifecycle
│   ├── handlers.ts       # MSW request handlers (mock API)
│   └── server.ts         # MSW node server
├── components/__tests__/
│   └── StatusBadge.test.tsx
└── utils/__tests__/
    ├── apiErrorHandler.test.ts
    └── utils.test.ts
```

## Linting & Type Checking

```bash
npm run lint          # ESLint (0 warnings policy)
npm run lint:fix      # Auto-fix ESLint issues
npm run type-check    # TypeScript strict check (no emit)
```

## Deployment to Vercel

1. Import the `frontend/` directory as a Vercel project (set root to `frontend/`)
2. Set the environment variable in Vercel project settings:
   - `VITE_API_URL` → your production API URL
3. Vercel will auto-detect Vite and run `npm run build` with output from `dist/`
4. SPA routing is handled by `vercel.json` rewrites

### Manual deploy via CLI

```bash
npm install -g vercel
vercel --prod
```

## Project Structure

```
src/
├── components/
│   ├── admin/          # Admin-specific components (MetricCard, Claim modals)
│   ├── documents/      # Document workflow (Upload, DraftsTab, Validation)
│   ├── layout/         # Header, Layout
│   ├── review/         # Review workflow (ReviewCard, ApproveModal, DecisionPanel)
│   ├── shared/         # ErrorBoundary, StatusBadge
│   ├── skeletons/      # Loading skeleton components (Card, Detail, Chart)
│   └── ui/             # shadcn/ui primitives (Button, Badge, Dialog, Skeleton, …)
├── hooks/
│   └── index.ts        # All TanStack Query hooks
├── lib/
│   ├── utils.ts        # cn(), formatDate(), formatDateTime(), truncate()
│   └── queryKeys.ts    # Query key factory
├── pages/
│   ├── documents/      # DocumentList, DocumentDetail, NewDocument
│   ├── review/         # ReviewQueue, ReviewDetail
│   ├── admin/          # AdminDashboard, ClaimRegistry
│   └── NotFound.tsx    # 404 page
├── providers/
│   ├── QueryProvider.tsx   # TanStack Query + Devtools
│   └── ToastProvider.tsx   # Toast notification context
├── services/
│   ├── api.ts          # Axios instance
│   ├── documents.ts    # Document API calls
│   ├── review.ts       # Review API calls
│   ├── claims.ts       # Claims CRUD
│   └── admin.ts        # Analytics computation utilities
├── test/               # Test setup & MSW handlers
├── types/              # TypeScript type definitions
└── utils/
    └── apiErrorHandler.ts  # HTTP error → user-friendly message
```

## Document Status Flow

```
DRAFT → VALIDATING → PASSED → HUMAN_REVIEW → APPROVED
                                           ↘ BLOCKED
```
