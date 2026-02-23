import type { AxiosError } from 'axios';

export interface ApiErrorResult {
  message: string;
  action?: () => void;
}

/**
 * Extracts a user-friendly message from an Axios error or network error.
 * Handles 404, 422, 500, network errors, and timeouts.
 */
export function handleApiError(error: unknown): ApiErrorResult {
  // Network error (no response received)
  if (!isAxiosError(error)) {
    const msg = error instanceof Error ? error.message : String(error);
    if (msg.toLowerCase().includes('network') || msg.toLowerCase().includes('failed to fetch')) {
      return { message: 'Connection lost. Please check your internet connection.' };
    }
    return { message: 'An unexpected error occurred. Please try again.' };
  }

  // Timeout
  if (error.code === 'ECONNABORTED' || error.message.toLowerCase().includes('timeout')) {
    return { message: 'Request timed out. The server is taking too long to respond.' };
  }

  // No response (offline / DNS failure)
  if (!error.response) {
    return { message: 'Connection lost. Please check your internet connection.' };
  }

  const { status, data } = error.response;

  if (status === 404) {
    return { message: 'The requested resource was not found.' };
  }

  if (status === 422) {
    // FastAPI / Django REST validation errors often have a `detail` array or object
    const detail = (data as Record<string, unknown>)?.detail;
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((d: unknown) => {
          if (typeof d === 'object' && d !== null && 'msg' in d) {
            const loc = Array.isArray((d as Record<string, unknown>).loc)
              ? ((d as Record<string, unknown>).loc as unknown[]).slice(1).join(' → ')
              : '';
            return loc ? `${loc}: ${(d as Record<string, unknown>).msg}` : String((d as Record<string, unknown>).msg);
          }
          return String(d);
        })
        .join('; ');
      return { message: `Validation error: ${msgs}` };
    }
    if (typeof detail === 'string') {
      return { message: `Validation error: ${detail}` };
    }
    // errors object (e.g. { title: 'Required' })
    const errors = (data as Record<string, unknown>)?.errors;
    if (errors && typeof errors === 'object') {
      const msgs = Object.entries(errors as Record<string, string>)
        .map(([field, msg]) => `${field}: ${msg}`)
        .join('; ');
      return { message: `Validation error: ${msgs}` };
    }
    return { message: 'Validation failed. Please check your input and try again.' };
  }

  if (status === 401) {
    return { message: 'You are not authorized to perform this action.' };
  }

  if (status === 403) {
    return { message: 'You do not have permission to access this resource.' };
  }

  if (status >= 500) {
    return { message: 'A server error occurred. Please try again later.' };
  }

  // Fallback for any other HTTP error
  const fallbackDetail = (data as Record<string, unknown>)?.detail ?? (data as Record<string, unknown>)?.message;
  if (typeof fallbackDetail === 'string') {
    return { message: fallbackDetail };
  }

  return { message: `Request failed with status ${status}.` };
}

// Type guard for AxiosError (avoids importing AxiosError at runtime)
function isAxiosError(err: unknown): err is AxiosError {
  return (
    typeof err === 'object' &&
    err !== null &&
    'isAxiosError' in err &&
    (err as Record<string, unknown>).isAxiosError === true
  );
}
