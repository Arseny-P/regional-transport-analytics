import { request } from '@/shared/api';
import type { Region, RegionList } from '../model/types';

export function listRegions(): Promise<RegionList> {
  return request('/regions');
}

export function getRegion(regionId: string): Promise<Region> {
  return request(`/regions/${encodeURIComponent(regionId)}`);
}
