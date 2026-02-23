import axios from 'axios';
import type { AxiosError, AxiosRequestConfig, AxiosResponse } from 'axios';

const API_URL = import.meta.env.VITE_API_URL;
if (!API_URL) {
  throw new Error('VITE_API_URL is not defined');
}

// LLM-backed endpoints (generate-draft, qa-iterate, extract-factsheet) can take
// up to 600 seconds (admin-configurable). Axios timeout is set to 10 minutes to
// accommodate the maximum configurable backend timeout + network overhead.
const api = axios.create({
  baseURL: API_URL,
  timeout: 600_000,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError) => {
    if (error.response?.status === 500) {
      console.error('Server error:', error.response.data);
    }
    if (error.response?.status === 401) {
      console.warn('Unauthorized - authentication will be added later');
    }
    return Promise.reject(error);
  }
);

export async function apiRequest<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await api.request<T>(config);
  return response.data;
}

export default api;
