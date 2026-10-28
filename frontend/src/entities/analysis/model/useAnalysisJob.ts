import { useEffect, useState } from 'react';
import { ApiError } from '@/shared/api';
import { getAnalysisResult, sendHeartbeat } from '../api/analysisApi';
import { isFinalState, type AnalysisResult, type AnalysisStatus } from './types';

const HEARTBEAT_INTERVAL_MS = 5000;

export function useAnalysisJob(jobId: string) {
  const [status, setStatus] = useState<AnalysisStatus | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [requestError, setRequestError] = useState<Error | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    let fetchedFor = '';

    const tick = async () => {
      try {
        const next = await sendHeartbeat(jobId);
        if (stopped) return;
        setStatus(next);
        setRequestError(null);

        const key = `${next.status}:${next.graph_available}:${next.metrics_available}`;
        if (key !== fetchedFor && (next.graph_available || isFinalState(next.status))) {
          const nextResult = await getAnalysisResult(jobId);
          if (stopped) return;
          setResult(nextResult);
          fetchedFor = key;
        }
        if (isFinalState(next.status)) return;
      } catch (err) {
        if (stopped) return;
        setRequestError(err as Error);
        if (err instanceof ApiError && err.status === 404) return;
      }
      timer = window.setTimeout(tick, HEARTBEAT_INTERVAL_MS);
    };

    tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [jobId]);

  return { status, result, requestError };
}
