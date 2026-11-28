import { useEffect, useRef, useState } from 'react';
import { ApiError } from '@/shared/api';
import { isRetryableAnalysisRequest } from '../lib/analysisErrorMessage';
import { cancelAnalysis, getAnalysisResult, sendHeartbeat } from '../api/analysisApi';
import { isFinalState, type AnalysisResult, type AnalysisStatus, type JobState } from './types';

const HEARTBEAT_INTERVAL_MS = 5000;
const RESULT_RETRY_DELAY_MS = 5000;
const MAX_HEARTBEAT_FAILURES_BEFORE_NOTICE = 3;
const MAX_RESULT_ATTEMPTS = 3;

interface RequestFailure {
  error: unknown;
  retrying: boolean;
}

type Cancellation =
  { type: 'idle' | 'sending' } | { type: 'failed' | 'already_finished'; error: unknown };

const IDLE_CANCELLATION: Cancellation = { type: 'idle' };

function canCancelStatus(status: JobState | undefined): boolean {
  return status === 'queued' || status === 'running';
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
  const [cancellation, setCancellation] = useState<Cancellation>(IDLE_CANCELLATION);
  const retryResultRef = useRef<(() => void) | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const heartbeatController = new AbortController();
    const jobController = new AbortController();
    let currentStatus: JobState | undefined;
    let cancelInFlight = false;
    let finishedBeforeCancel = false;
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

    function acceptStatus(data: AnalysisStatus) {
      const final = isFinalState(data.status);
      if (
        (currentStatus && isFinalState(currentStatus) && currentStatus !== data.status) ||
        (currentStatus === 'cancel_requested' && canCancelStatus(data.status)) ||
        (finishedBeforeCancel && !final)
      ) {
        return false;
      }

      currentStatus = data.status;
      setStatus(data);
      if (data.status === 'cancel_requested' || final) setCancellation(IDLE_CANCELLATION);
      if (final) stopHeartbeat();
      return true;
    }

    async function loadResult() {
      if (jobController.signal.aborted || resultInFlight || wantedResult === fetchedResult) {
        return;
      }

      const requestedResult = wantedResult;
      resultInFlight = true;
      resultAttempts++;

      try {
        const data = await getAnalysisResult(jobId, jobController.signal);
        if (jobController.signal.aborted) return;

        setResult(data);
        const receivedResult = resultKey(data);
        if (isFinalState(data.status) && acceptStatus(data)) {
          setHeartbeatFailure(null);
          wantedResult = receivedResult;
        }
        fetchedResult = receivedResult === wantedResult ? receivedResult : requestedResult;
        if (fetchedResult === wantedResult) {
          setResultFailure(null);
          setIsLoadingResult(false);
        }
      } catch (error) {
        if (jobController.signal.aborted || requestedResult !== wantedResult) return;

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

    function receiveStatus(data: AnalysisStatus) {
      if (
        acceptStatus(data) &&
        (data.graph_available || data.metrics_available || isFinalState(data.status))
      ) {
        requestResult(data);
      }
    }

    async function beat() {
      if (heartbeatController.signal.aborted) return;
      const sequence = ++sentHeartbeats;
      try {
        const data = await sendHeartbeat(jobId, heartbeatController.signal);
        if (heartbeatController.signal.aborted || sequence <= lastHandledHeartbeat) return;

        lastHandledHeartbeat = sequence;
        heartbeatFailures = 0;
        setHeartbeatFailure(null);
        receiveStatus(data);
      } catch (error) {
        if (heartbeatController.signal.aborted || sequence <= lastHandledHeartbeat) return;

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

    async function cancel() {
      if (!canCancelStatus(currentStatus) || cancelInFlight || finishedBeforeCancel) return;

      cancelInFlight = true;
      setCancellation({ type: 'sending' });
      try {
        const data = await cancelAnalysis(jobId, jobController.signal);
        if (jobController.signal.aborted) return;

        lastHandledHeartbeat = sentHeartbeats;
        setHeartbeatFailure(null);
        heartbeatFailures = 0;
        receiveStatus(data);
      } catch (error) {
        if (jobController.signal.aborted || !canCancelStatus(currentStatus)) return;

        if (
          error instanceof ApiError &&
          error.status === 409 &&
          error.code === 'job_already_finished'
        ) {
          finishedBeforeCancel = true;
          lastHandledHeartbeat = sentHeartbeats;
          setCancellation({ type: 'already_finished', error });
          void beat();
        } else {
          setCancellation({ type: 'failed', error });
        }
      } finally {
        cancelInFlight = false;
      }
    }

    cancelRef.current = () => void cancel();
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
      jobController.abort();
      clearResultRetry();
      cancelRef.current = null;
      retryResultRef.current = null;
    };
  }, [jobId]);

  return {
    status,
    result,
    heartbeatFailure,
    resultFailure,
    isLoadingResult,
    cancellation,
    cancel: () => cancelRef.current?.(),
    retryResult: () => retryResultRef.current?.(),
  };
}
