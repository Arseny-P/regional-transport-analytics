import { useEffect, useMemo } from 'react';
import { geoJSON } from 'leaflet';
import { GeoJSON, useMap } from 'react-leaflet';
import type { Region } from '../model/types';

export function RegionBoundary({ region }: { region: Region }) {
  const map = useMap();
  const bounds = useMemo(() => geoJSON(region.boundary).getBounds(), [region]);

  useEffect(() => {
    map.fitBounds(bounds, { padding: [40, 40] });
  }, [map, bounds]);

  return (
    <GeoJSON
      key={region.region_id}
      data={region.boundary}
      interactive={false}
      style={{ color: '#0f62fe', weight: 2, fillOpacity: 0.05 }}
    />
  );
}
