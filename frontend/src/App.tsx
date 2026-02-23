
import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import QueryProvider from '@/providers/QueryProvider';
import { ToastProvider } from '@/providers/ToastProvider';
import Layout from '@/components/layout/Layout';
import ErrorBoundary from '@/components/shared/ErrorBoundary';

const DocumentList = lazy(() => import('@/pages/documents/DocumentList'));
const DocumentDetail = lazy(() => import('@/pages/documents/DocumentDetail'));
const NewDocument = lazy(() => import('@/pages/documents/NewDocument'));
const ReviewQueue = lazy(() => import('@/pages/review/ReviewQueue'));
const ReviewDetail = lazy(() => import('@/pages/review/ReviewDetail'));
const AdminDashboard = lazy(() => import('@/pages/admin/AdminDashboard'));
const NotFound = lazy(() => import('@/pages/NotFound'));

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center h-screen">
      <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary" />
    </div>
  );
}

function App() {
  return (
    <QueryProvider>
      <ToastProvider>
        <BrowserRouter>
          <ErrorBoundary>
            <Layout>
              <Suspense fallback={<LoadingFallback />}>
                <Routes>
                  <Route path="/" element={<Navigate to="/documents" replace />} />
                  <Route path="/documents" element={<DocumentList />} />
                  <Route path="/documents/new" element={<NewDocument />} />
                  <Route path="/documents/:id" element={<DocumentDetail />} />
                  <Route path="/review" element={<ReviewQueue />} />
                  <Route path="/review/:id" element={<ReviewDetail />} />
                  <Route path="/admin" element={<AdminDashboard />} />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </Layout>
          </ErrorBoundary>
        </BrowserRouter>
      </ToastProvider>
    </QueryProvider>
  );
}

export default App;
