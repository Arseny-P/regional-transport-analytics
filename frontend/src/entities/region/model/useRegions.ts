import { useEffect, useState } from 'react';
import { getRegion, listRegions } from '../api/regionApi';
import type { Region, RegionList, RegionSummary } from './types';

function mergeRegions(regions: RegionList, added: RegionList): RegionList {
  const byId = new Map(regions.map((region) => [region.region_id, region]));
  for (const region of added) {
    byId.set(region.region_id, region);
  }
  return [...byId.values()];
}

export function useRegions() {
  const [regions, setRegions] = useState<RegionList | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listRegions(controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) {
          setRegions((current) => mergeRegions(next, current ?? []));
        }
      })
      .catch((err: Error) => !controller.signal.aborted && setError(err));
    return () => controller.abort();
  }, [attempt]);

  function retry() {
    setError(null);
    setAttempt((current) => current + 1);
  }

  function addRegion(region: RegionSummary) {
    setRegions((current) => mergeRegions(current ?? [], [region]));
  }

  return { regions, error, addRegion, retry };
}

export function useRegion(regionId: string | null) {
  const [region, setRegion] = useState<Region | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setRegion(null);
    setError(null);
    if (!regionId) return;

    const controller = new AbortController();
    getRegion(regionId, controller.signal)
      .then((next) => !controller.signal.aborted && setRegion(next))
      .catch((err: Error) => !controller.signal.aborted && setError(err));
    return () => controller.abort();
  }, [regionId, attempt]);

  function retry() {
    setError(null);
    setAttempt((current) => current + 1);
  }

  return { region: region?.region_id === regionId ? region : null, error, retry };
}
