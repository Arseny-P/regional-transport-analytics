import { useState } from 'react';
import type { BBox } from '@/entities/area';
import type { TransportMode } from '@/entities/transport-mode';
import { ApiError } from '@/shared/api';
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

export function useRunAnalysis() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (regionId: string, area: BBox, transports: TransportMode[]) => {
    setIsLoading(true);
    setError(null);
    try {
      return await createWithRetry(crypto.randomUUID(), {
        region_id: regionId,
        area: toAnalysisArea(area),
        transports,
      });
    } catch (err) {
      setError(errorMessage(err as Error));
    } finally {
      setIsLoading(false);
    }
  };

  return { run, isLoading, error };
}
