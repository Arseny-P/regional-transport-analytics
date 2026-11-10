import type { JobState } from '@/entities/analysis';
import type { TransportMode } from '@/entities/transport-mode';
import { request } from '@/shared/api';

interface MapPoint {
  latitude: number;
  longitude: number;
}

export interface AnalysisArea {
  first_point: MapPoint;
  second_point: MapPoint;
}

export interface CreateAnalysisRequest {
  region_id: string;
  area: AnalysisArea;
  transports: TransportMode[];
}

export interface AnalysisReceipt {
  job_id: string;
  status: JobState;
}

export function createAnalysis(
  jobId: string,
  body: CreateAnalysisRequest
): Promise<AnalysisReceipt> {
  return request('/analysis', { method: 'POST', params: { job_id: jobId }, body });
}
