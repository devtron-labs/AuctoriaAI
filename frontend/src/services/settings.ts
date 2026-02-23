import { apiRequest } from './api';
import type { KnownLlmModel, SystemSettings, SystemSettingsUpdate, WebhookTestResult } from '@/types/admin';

export function getAvailableModels(): Promise<KnownLlmModel[]> {
  return apiRequest<KnownLlmModel[]>({
    method: 'GET',
    url: '/admin/settings/available-models',
  });
}

export function getSettings(): Promise<SystemSettings> {
  return apiRequest<SystemSettings>({
    method: 'GET',
    url: '/admin/settings',
  });
}

export function updateSettings(data: SystemSettingsUpdate): Promise<SystemSettings> {
  return apiRequest<SystemSettings>({
    method: 'PUT',
    url: '/admin/settings',
    data,
  });
}

export function testWebhook(): Promise<WebhookTestResult> {
  return apiRequest<WebhookTestResult>({
    method: 'POST',
    url: '/admin/settings/test-webhook',
  });
}
