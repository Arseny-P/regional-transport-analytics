import { useEffect, useState } from 'react';
import { isRetryableAnalysisRequest } from '../lib/analysisErrorMessage';
import { getAnalysisResult, sendHeartbeat } from '../api/analysisApi';
import { isFinalState, type AnalysisResult, type AnalysisStatus } from './types';

const HEARTBEAT_INTERVAL_MS = 5000;

export function useAnalysisJob(jobId: string) {
  const [status, setStatus] = useState<AnalysisStatus | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [requestError, setRequestError] = useState<Error | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let stopped = false,
      terminal = false,
      busy = false;
    let wanted = '',
      fetched = '',
      sent = 0,
      accepted = 0;
    let retry: number | undefined;
    const fail = (err: unknown) => {
      if (stopped) return;
      setRequestError(err as Error);
      if (!isRetryableAnalysisRequest(err)) {
        stopped = true;
        window.clearInterval(timer);
        window.clearTimeout(retry);
      }
    };
    const load = async () => {
      if (stopped || busy || !wanted || wanted === fetched) return;
      busy = true;
      const key = wanted;
      try {
        const data = await getAnalysisResult(jobId, controller.signal);
        if (stopped) return;
        setResult(data);
        fetched = key;
        setRequestError(null);
        if (isFinalState(data.status)) {
          terminal = true;
          setStatus(data);
          window.clearInterval(timer);
        }
      } catch (err) {
        fail(err);
      } finally {
        busy = false;
        if (!stopped && wanted !== fetched)
          retry = window.setTimeout(() => {
            void load();
          }, HEARTBEAT_INTERVAL_MS);
      }
    };
    const beat = async () => {
      if (stopped || terminal) return;
      const sequence = ++sent;
      try {
        const data = await sendHeartbeat(jobId, controller.signal);
        if (stopped || terminal || sequence < accepted) return;
        accepted = sequence;
        setStatus(data);
        setRequestError(null);
        if (isFinalState(data.status)) {
          terminal = true;
          window.clearInterval(timer);
        }
        if (data.graph_available || data.metrics_available || terminal) {
          wanted = [data.status, data.graph_available, data.metrics_available].join(':');
          void load();
        }
      } catch (err) {
        fail(err);
      }
    };
    const timer = window.setInterval(() => {
      void beat();
    }, HEARTBEAT_INTERVAL_MS);
    void beat();
    return () => {
      stopped = true;
      controller.abort();
      window.clearInterval(timer);
      window.clearTimeout(retry);
    };
  }, [jobId]);
  return { status, result, requestError };
}
