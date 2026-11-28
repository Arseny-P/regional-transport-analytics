import { useEffect, useRef, useState } from 'react';
import { isRetryableAnalysisRequest } from '../lib/analysisErrorMessage';
import { getAnalysisResult, sendHeartbeat } from '../api/analysisApi';
import { isFinalState, type AnalysisResult, type AnalysisStatus } from './types';

const HEARTBEAT_INTERVAL_MS = 5000;
const RESULT_RETRY_DELAY_MS = 5000;
const MAX_HEARTBEAT_FAILURES_BEFORE_NOTICE = 3;
const MAX_RESULT_ATTEMPTS = 3;

interface RequestFailure {
  error: unknown;
  retrying: boolean;
}

function resultKey({ status, graph_available, metrics_available }: AnalysisStatus): string {
  return [status, graph_available, metrics_available].join(':');
}

export function useAnalysisJob(jobId: string) {
  const [status, setStatus] = useState<AnalysisStatus | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [heartbeatFailure, setHeartbeatFailure] = useState<RequestFailure | null>(null);
  const [resultFailure, setResultFailure] = useState<RequestFailure | null>(null);
  const [isLoadingResult, setIsLoadingResult] = useState(false);
  const retryResultRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const heartbeatController = new AbortController();
    const resultController = new AbortController();
    let sentHeartbeats = 0;
    let lastHandledHeartbeat = 0;
    let heartbeatFailures = 0;
    let wantedResult = '';
    let fetchedResult = '';
    let resultInFlight = false;
    let resultAttempts = 0;
    let resultRetryTimer: number | undefined;

    function stopHeartbeat() {
      window.clearInterval(heartbeatTimer);
      heartbeatController.abort();
    }

    function clearResultRetry() {
      window.clearTimeout(resultRetryTimer);
      resultRetryTimer = undefined;
    }

    async function loadResult() {
      if (resultController.signal.aborted || resultInFlight || wantedResult === fetchedResult) {
        return;
      }

      const requestedResult = wantedResult;
      resultInFlight = true;
      resultAttempts++;

      try {
        const data = await getAnalysisResult(jobId, resultController.signal);
        if (resultController.signal.aborted) return;

        setResult(data);
        const receivedResult = resultKey(data);
        if (isFinalState(data.status)) {
          stopHeartbeat();
          setHeartbeatFailure(null);
          setStatus(data);
          wantedResult = receivedResult;
        }
        fetchedResult = receivedResult === wantedResult ? receivedResult : requestedResult;
        if (fetchedResult === wantedResult) {
          setResultFailure(null);
          setIsLoadingResult(false);
        }
      } catch (error) {
        if (resultController.signal.aborted || requestedResult !== wantedResult) return;

        const retrying = isRetryableAnalysisRequest(error) && resultAttempts < MAX_RESULT_ATTEMPTS;
        setResultFailure({ error, retrying });
        setIsLoadingResult(retrying);
        if (retrying) {
          resultRetryTimer = window.setTimeout(() => {
            resultRetryTimer = undefined;
            void loadResult();
          }, RESULT_RETRY_DELAY_MS);
        }
      } finally {
        resultInFlight = false;
        if (requestedResult !== wantedResult) void loadResult();
      }
    }

    function requestResult(data: AnalysisStatus) {
      const nextResult = resultKey(data);
      if (nextResult === wantedResult) return;

      wantedResult = nextResult;
      resultAttempts = 0;
      clearResultRetry();
      setResultFailure(null);
      setIsLoadingResult(wantedResult !== fetchedResult);
      void loadResult();
    }

    async function beat() {
      const sequence = ++sentHeartbeats;
      try {
        const data = await sendHeartbeat(jobId, heartbeatController.signal);
        if (heartbeatController.signal.aborted || sequence < lastHandledHeartbeat) return;

        lastHandledHeartbeat = sequence;
        heartbeatFailures = 0;
        setHeartbeatFailure(null);
        setStatus(data);
        const final = isFinalState(data.status);
        if (final) stopHeartbeat();
        if (data.graph_available || data.metrics_available || final) requestResult(data);
      } catch (error) {
        if (heartbeatController.signal.aborted || sequence < lastHandledHeartbeat) return;

        lastHandledHeartbeat = sequence;
        heartbeatFailures++;
        const retryable = isRetryableAnalysisRequest(error);
        setHeartbeatFailure({
          error,
          retrying: retryable && heartbeatFailures < MAX_HEARTBEAT_FAILURES_BEFORE_NOTICE,
        });
        if (!retryable) stopHeartbeat();
      }
    }

    retryResultRef.current = () => {
      if (
        resultInFlight ||
        resultAttempts < MAX_RESULT_ATTEMPTS ||
        wantedResult === fetchedResult
      ) {
        return;
      }

      resultAttempts = 0;
      setResultFailure(null);
      setIsLoadingResult(true);
      void loadResult();
    };

    const heartbeatTimer = window.setInterval(() => void beat(), HEARTBEAT_INTERVAL_MS);
    void beat();
    return () => {
      stopHeartbeat();
      resultController.abort();
      clearResultRetry();
      retryResultRef.current = null;
    };
  }, [jobId]);

  return {
    status,
    result,
    heartbeatFailure,
    resultFailure,
    isLoadingResult,
    retryResult: () => retryResultRef.current?.(),
  };
}
