import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';
import { AlertCircle, AlertTriangle, CheckCircle, X, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

export type ToastType = 'success' | 'error' | 'info' | 'warning';

interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
  warning: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idRef = useRef(0);

  const toast = useCallback((message: string, type: ToastType = 'info') => {
    const id = String(++idRef.current);
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const success = useCallback((message: string) => toast(message, 'success'), [toast]);
  const error = useCallback((message: string) => toast(message, 'error'), [toast]);
  const info = useCallback((message: string) => toast(message, 'info'), [toast]);
  const warning = useCallback((message: string) => toast(message, 'warning'), [toast]);

  const dismiss = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return (
    <ToastContext.Provider value={{ toast, success, error, info, warning }}>
      {children}
      <div
        className="fixed top-4 right-4 z-50 flex flex-col gap-2 w-80 pointer-events-none"
        role="region"
        aria-label="Notifications"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="alert"
            className={cn(
              'flex items-start gap-3 p-4 rounded-lg shadow-lg border text-sm pointer-events-auto animate-in slide-in-from-right-full duration-200',
              t.type === 'success' && 'bg-green-50 border-green-200 text-green-800',
              t.type === 'error' && 'bg-red-50 border-red-200 text-red-800',
              t.type === 'info' && 'bg-blue-50 border-blue-200 text-blue-800',
              t.type === 'warning' && 'bg-amber-50 border-amber-200 text-amber-800',
            )}
          >
            {t.type === 'success' && <CheckCircle className="h-4 w-4 mt-0.5 shrink-0" aria-hidden="true" />}
            {t.type === 'error' && <XCircle className="h-4 w-4 mt-0.5 shrink-0" aria-hidden="true" />}
            {t.type === 'info' && <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" aria-hidden="true" />}
            {t.type === 'warning' && <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" aria-hidden="true" />}
            <span className="flex-1">{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              className="shrink-0 opacity-60 hover:opacity-100 transition-opacity focus:outline-none focus:ring-2 focus:ring-current rounded"
              aria-label="Dismiss notification"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
