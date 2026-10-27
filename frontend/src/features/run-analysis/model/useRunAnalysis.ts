import { useState } from 'react';
import type { BBox } from '@/entities/area';
import type { TransportMode } from '@/entities/transport-mode';
import { ApiError } from '@/shared/api';
import { DEFAULT_REGION_ID } from '@/shared/config';
import { createAnalysis, type CreateAnalysisRequest } from '../api/createAnalysis';
import { errorMessage } from '../lib/errorMessage';
import { toAnalysisArea } from '../lib/toAnalysisArea';

const MAX_ATTEMPTS = 3;

async function createWithRetry(jobId: string, body: CreateAnalysisRequest, attempt = 1) {
  try {
    return await createAnalysis(jobId, body);
  } catch (err) {
    if (err instanceof ApiError || attempt >= MAX_ATTEMPTS) throw err;
    return createWithRetry(jobId, body, attempt + 1);
  }
}

export function useRunAnalysis(onSuccess: (jobId: string) => void) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (area: BBox, transports: TransportMode[]) => {
    setIsLoading(true);
    setError(null);
    try {
      const receipt = await createWithRetry(crypto.randomUUID(), {
        region_id: DEFAULT_REGION_ID,
        area: toAnalysisArea(area),
        transports,
      });
      onSuccess(receipt.job_id);
    } catch (err) {
      setError(errorMessage(err as Error));
      setIsLoading(false);
    }
  };

  return { run, isLoading, error };
}
