import { MapContainer, TileLayer } from 'react-leaflet';
import type { LatLngTuple } from 'leaflet';
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
  return (
    <MapContainer
      center={center}
      zoom={zoom}
      style={{ width: '100%', height: '100vh' }}
      zoomControl={false}
    >
      <TileLayer url={OSM_TILE_URL} attribution="" />

      <SelectArea
        onChange={onAreaSelect}
        point1={point1}
        point2={point2}
        setPoint1={setPoint1}
        setPoint2={setPoint2}
      />
    </MapContainer>
  );
}
