import { request } from '@/shared/api';
import type { AnalysisResult, AnalysisStatus } from '../model/types';

export function sendHeartbeat(jobId: string, signal?: AbortSignal): Promise<AnalysisStatus> {
  return request('/analysis/heartbeat', { method: 'POST', signal, params: { job_id: jobId } });
}

export function getAnalysisResult(jobId: string, signal?: AbortSignal): Promise<AnalysisResult> {
  return request('/analysis/result', { signal, params: { job_id: jobId } });
}
