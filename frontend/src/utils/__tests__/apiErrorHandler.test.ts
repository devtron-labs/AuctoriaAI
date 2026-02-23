import { handleApiError } from '../apiErrorHandler';

// Helper to create a minimal AxiosError-like object
function axiosError(status: number, data: unknown = {}) {
  return {
    isAxiosError: true,
    code: undefined as string | undefined,
    message: `Request failed with status code ${status}`,
    response: { status, data },
  };
}

describe('handleApiError', () => {
  it('returns not-found message for 404 errors', () => {
    const result = handleApiError(axiosError(404));
    expect(result.message).toMatch(/not found/i);
  });

  it('extracts FastAPI detail array from 422 response', () => {
    const detail = [{ loc: ['body', 'title'], msg: 'Required', type: 'value_error' }];
    const result = handleApiError(axiosError(422, { detail }));
    expect(result.message).toMatch(/title/i);
    expect(result.message).toMatch(/Required/);
  });

  it('extracts string detail from 422 response', () => {
    const result = handleApiError(axiosError(422, { detail: 'Invalid input' }));
    expect(result.message).toMatch(/Invalid input/);
  });

  it('extracts errors object from 422 response', () => {
    const result = handleApiError(axiosError(422, { errors: { title: 'Too long' } }));
    expect(result.message).toMatch(/title/);
    expect(result.message).toMatch(/Too long/);
  });

  it('returns generic validation message for 422 with no detail', () => {
    const result = handleApiError(axiosError(422, {}));
    expect(result.message).toMatch(/validation/i);
  });

  it('returns server error message for 500', () => {
    const result = handleApiError(axiosError(500));
    expect(result.message).toMatch(/server error/i);
  });

  it('returns server error message for 503', () => {
    const result = handleApiError(axiosError(503));
    expect(result.message).toMatch(/server error/i);
  });

  it('returns unauthorized message for 401', () => {
    const result = handleApiError(axiosError(401));
    expect(result.message).toMatch(/not authorized/i);
  });

  it('returns forbidden message for 403', () => {
    const result = handleApiError(axiosError(403));
    expect(result.message).toMatch(/permission/i);
  });

  it('returns connection message for network errors (no response)', () => {
    const error = { isAxiosError: true, code: undefined, message: 'Network Error', response: undefined };
    const result = handleApiError(error);
    expect(result.message).toMatch(/connection/i);
  });

  it('returns timeout message for ECONNABORTED errors', () => {
    const error = {
      isAxiosError: true,
      code: 'ECONNABORTED',
      message: 'timeout of 120000ms exceeded',
      response: undefined,
    };
    const result = handleApiError(error);
    expect(result.message).toMatch(/timed out/i);
  });

  it('returns connection message for generic Error with "network" in message', () => {
    const result = handleApiError(new Error('Network request failed'));
    expect(result.message).toMatch(/connection/i);
  });

  it('returns fallback message for unknown errors', () => {
    const result = handleApiError(new Error('Something broke'));
    expect(result.message).toBeTruthy();
  });

  it('uses detail string from non-5xx non-4xx response body', () => {
    const result = handleApiError(axiosError(409, { detail: 'Conflict' }));
    expect(result.message).toMatch(/Conflict/);
  });
});
