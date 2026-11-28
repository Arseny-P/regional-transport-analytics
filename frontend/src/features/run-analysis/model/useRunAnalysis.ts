import { useEffect, useRef, useState } from 'react';
import type { BBox } from '@/entities/area';
import type { TransportMode } from '@/entities/transport-mode';
import { ApiError } from '@/shared/api';
import { createAnalysis, type CreateAnalysisRequest } from '../api/createAnalysis';
import { errorMessage } from '../lib/errorMessage';
import { toAnalysisArea } from '../lib/toAnalysisArea';

const MAX_ATTEMPTS = 3;

async function createWithRetry(
  jobId: string,
  body: CreateAnalysisRequest,
  signal: AbortSignal,
  attempt = 1
) {
  try {
    return await createAnalysis(jobId, body, signal);
  } catch (err) {
    if (signal.aborted || err instanceof ApiError || attempt >= MAX_ATTEMPTS) throw err;
    return createWithRetry(jobId, body, signal, attempt + 1);
  }
}

export function useRunAnalysis() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => activeRequest.current?.abort(), []);

  const run = async (regionId: string, area: BBox, transports: TransportMode[]) => {
    if (activeRequest.current) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    setIsLoading(true);
    setError(null);
    try {
      const receipt = await createWithRetry(
        crypto.randomUUID(),
        { region_id: regionId, area: toAnalysisArea(area), transports },
        controller.signal
      );
      if (!controller.signal.aborted) return receipt;
    } catch (err) {
      if (!controller.signal.aborted) setError(errorMessage(err));
    } finally {
      activeRequest.current = null;
      if (!controller.signal.aborted) setIsLoading(false);
    }
  };

  return { run, isLoading, error };
}
