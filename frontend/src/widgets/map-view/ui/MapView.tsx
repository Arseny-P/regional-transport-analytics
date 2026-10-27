import type { ReactNode } from 'react';
import { MapContainer, TileLayer } from 'react-leaflet';
import type { LatLngTuple } from 'leaflet';
import { DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM, OSM_TILE_URL } from '@/shared/config';
import styles from './MapView.module.css';

interface MapViewProps {
  center?: LatLngTuple;
  zoom?: number;
  children?: ReactNode;
}

export function MapView({
  center = DEFAULT_MAP_CENTER,
  zoom = DEFAULT_MAP_ZOOM,
  children,
}: MapViewProps) {
  return (
    <MapContainer center={center} zoom={zoom} className={styles.map} zoomControl={false}>
      <TileLayer url={OSM_TILE_URL} attribution="" />
      {children}
    </MapContainer>
  );
}
