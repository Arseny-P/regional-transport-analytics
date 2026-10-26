import { useEffect, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON } from 'react-leaflet';
import * as L from 'leaflet';
import type { LatLngTuple } from 'leaflet';
import type { FeatureCollection } from 'geojson';
import type { BBox } from '@/entities/area';
import { SelectArea } from '@/features/select-area';
import { DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM, OSM_TILE_URL } from '@/shared/config';

interface MapViewProps {
  center?: LatLngTuple;
  zoom?: number;
  onAreaSelect: (area: BBox | null) => void;
  point1: string;
  point2: string;
  setPoint1: (value: string) => void;
  setPoint2: (value: string) => void;
}

export function MapView({
  center = DEFAULT_MAP_CENTER,
  zoom = DEFAULT_MAP_ZOOM,
  onAreaSelect,
  point1,
  point2,
  setPoint1,
  setPoint2,
}: MapViewProps) {
  const [geojsonData, setGeojsonData] = useState<FeatureCollection | null>(null);

  useEffect(() => {
    fetch('/kronshtadt_logistics.geojson')
      .then((r) => r.json())
      .then((data) => setGeojsonData(data))
      .catch((err) => console.error('GeoJSON load error:', err));
  }, []);

  return (
    <MapContainer center={center} zoom={zoom} style={{ width: '100%', height: '100vh' }} zoomControl={false}>
      <TileLayer url={OSM_TILE_URL} attribution="" />
      {geojsonData && (
        <GeoJSON
          data={geojsonData}
          style={() => ({ color: '#ff3333', weight: 3, opacity: 0.8 })}
          pointToLayer={(feature, latlng) => {
            if (feature?.geometry?.type === 'Point') {
              return L.circleMarker(latlng, {
                radius: 8, fillColor: '#0066cc', color: '#fff', weight: 2, fillOpacity: 0.9,
              }).bindPopup(feature.properties?.name || 'Объект');
            }
            return L.marker(latlng);
          }}
        />
      )}
      <SelectArea onChange={onAreaSelect} point1={point1} point2={point2} setPoint1={setPoint1} setPoint2={setPoint2} />
    </MapContainer>
  );
}