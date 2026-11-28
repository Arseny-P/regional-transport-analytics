import { request } from '@/shared/api';
import type { Region, RegionList } from '../model/types';

export function listRegions(signal?: AbortSignal): Promise<RegionList> {
  return request('/regions', { signal });
}

export function getRegion(regionId: string, signal?: AbortSignal): Promise<Region> {
  return request(`/regions/${encodeURIComponent(regionId)}`, { signal });
}

export function uploadRegion(file: File): Promise<Region> {
  const body = new FormData();
  body.append('file', file);
  return request('/regions', { method: 'POST', body });
}
