import { Link } from 'react-router-dom';
import { FileSearch } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center px-4">
      <FileSearch className="h-16 w-16 text-gray-300 mb-6" aria-hidden="true" />
      <h1 className="text-6xl font-bold text-gray-200 mb-4" aria-hidden="true">404</h1>
      <h2 className="text-2xl font-semibold text-gray-900 mb-3">Page Not Found</h2>
      <p className="text-gray-500 text-sm mb-8 max-w-sm">
        The page you are looking for doesn&apos;t exist or may have been moved.
      </p>
      <Link
        to="/documents"
        className="inline-flex items-center px-5 py-2.5 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-opacity"
      >
        Go to Documents
      </Link>
    </div>
  );
}
