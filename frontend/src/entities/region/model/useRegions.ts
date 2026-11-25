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

  useEffect(() => {
    let stopped = false;
    listRegions()
      .then((next) => !stopped && setRegions((current) => mergeRegions(next, current ?? [])))
      .catch((err: Error) => !stopped && setError(err));
    return () => {
      stopped = true;
    };
  }, []);

  function addRegion(region: RegionSummary) {
    setRegions((current) => mergeRegions(current ?? [], [region]));
  }

  return { regions, error, addRegion };
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
