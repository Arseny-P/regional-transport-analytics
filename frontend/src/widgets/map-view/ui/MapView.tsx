import { useEffect, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON } from 'react-leaflet';
import * as L from 'leaflet';
import type { LatLngTuple } from 'leaflet';
import type { FeatureCollection } from 'geojson';
import type { BBox } from '@/entities/area';
import { SelectArea } from '@/features/select-area';
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
  const [kronshtadtGraph, setKronshtadtGraph] = useState<FeatureCollection | null>(null);
  const [shusharyGraph, setShusharyGraph] = useState<FeatureCollection | null>(null);

  useEffect(() => {
    fetch('/kronshtadt_logistics.geojson')
      .then((r) => r.json())
      .then((data) => setKronshtadtGraph(data))
      .catch((err) => console.error('Ошибка загрузки графа Кронштадта:', err));

    fetch('/shushary_logistics.geojson')
      .then((r) => r.json())
      .then((data) => setShusharyGraph(data))
      .catch((err) => console.error('Ошибка загрузки графа Шушар:', err));
  }, []);

  return (
    <MapContainer center={center} zoom={zoom} className={styles.map} zoomControl={false}>
      <TileLayer url={OSM_TILE_URL} attribution="" />

      {/* КРОНШТАДТ - синий */}
      {kronshtadtGraph && (
        <GeoJSON
          data={kronshtadtGraph}
          style={(feature) => {
            if (feature?.geometry?.type === 'LineString') {
              return { color: '#0066cc', weight: 3, opacity: 0.6 };
            }
            return {};
          }}
          pointToLayer={(feature, latlng) => {
            if (feature?.geometry?.type === 'Point') {
              return L.circleMarker(latlng, {
                radius: 8, fillColor: '#0066cc', color: '#fff', weight: 2, fillOpacity: 0.9,
              }).bindPopup(`<b>${feature.properties?.name}</b><br/><small>(Кронштадт)</small>`);
            }
            return L.marker(latlng);
          }}
        />
      )}

      {/* ШУШАРЫ - красный */}
      {shusharyGraph && (
        <GeoJSON
          data={shusharyGraph}
          style={(feature) => {
            if (feature?.geometry?.type === 'LineString') {
              return { color: '#ff3333', weight: 3, opacity: 0.6 };
            }
            return {};
          }}
          pointToLayer={(feature, latlng) => {
            if (feature?.geometry?.type === 'Point') {
              return L.circleMarker(latlng, {
                radius: 8, fillColor: '#ff3333', color: '#fff', weight: 2, fillOpacity: 0.9,
              }).bindPopup(`<b>${feature.properties?.name}</b><br/><small>(Шушары)</small>`);
            }
            return L.marker(latlng);
          }}
        />
      )}

      {/* ЛЕГЕНДА */}
      <div style={{ position: 'absolute', bottom: '20px', right: '20px', backgroundColor: 'white', padding: '15px', borderRadius: '8px', boxShadow: '0 2px 8px rgba(0,0,0,0.3)', zIndex: 1000, fontSize: '14px' }}>
        <div style={{ marginBottom: '10px', fontWeight: 'bold' }}>Легенда:</div>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '8px' }}>
          <div style={{ width: '12px', height: '12px', borderRadius: '50%', backgroundColor: '#0066cc', border: '2px solid white', marginRight: '8px' }}></div>
          <span>Кронштадт</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <div style={{ width: '12px', height: '12px', borderRadius: '50%', backgroundColor: '#ff3333', border: '2px solid white', marginRight: '8px' }}></div>
          <span>Шушары</span>
        </div>
      </div>

      <SelectArea onChange={onAreaSelect} point1={point1} point2={point2} setPoint1={setPoint1} setPoint2={setPoint2} />
    </MapContainer>
  );
}