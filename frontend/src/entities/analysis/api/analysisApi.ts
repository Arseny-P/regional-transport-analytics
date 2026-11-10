import { request } from '@/shared/api';
import type { AnalysisResult, AnalysisStatus } from '../model/types';

export function sendHeartbeat(jobId: string): Promise<AnalysisStatus> {
  return request('/analysis/heartbeat', { method: 'POST', params: { job_id: jobId } });
}

export function getAnalysisResult(jobId: string): Promise<AnalysisResult> {
  return request('/analysis/result', { params: { job_id: jobId } });
}
