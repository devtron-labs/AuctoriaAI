import { apiRequest } from '@/services/api';
import type { Claim, CreateClaimRequest, UpdateClaimRequest } from '@/types/admin';

export function getClaims(): Promise<Claim[]> {
  return apiRequest<Claim[]>({ method: 'GET', url: '/claims' });
}

export function createClaim(data: CreateClaimRequest): Promise<Claim> {
  return apiRequest<Claim>({ method: 'POST', url: '/claims', data });
}

export function updateClaim(id: string, data: UpdateClaimRequest): Promise<Claim> {
  return apiRequest<Claim>({ method: 'PUT', url: `/claims/${id}`, data });
}

export function deleteClaim(id: string): Promise<void> {
  return apiRequest<void>({ method: 'DELETE', url: `/claims/${id}` });
}
