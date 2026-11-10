import { useEffect, useState } from 'react';
import { getRegion, listRegions } from '../api/regionApi';
import type { Region, RegionList } from './types';

export function useRegions() {
  const [regions, setRegions] = useState<RegionList | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let stopped = false;
    listRegions()
      .then((next) => !stopped && setRegions(next))
      .catch((err: Error) => !stopped && setError(err));
    return () => {
      stopped = true;
    };
  }, []);

  return { regions, error };
}

export function useRegion(regionId: string | null) {
  const [region, setRegion] = useState<Region | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    setRegion(null);
    setError(null);
    if (!regionId) return;

    let stopped = false;
    getRegion(regionId)
      .then((next) => !stopped && setRegion(next))
      .catch((err: Error) => !stopped && setError(err));
    return () => {
      stopped = true;
    };
  }, [regionId]);

  return { region, error };
}
