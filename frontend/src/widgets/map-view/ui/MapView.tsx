import { useEffect, useState, type ReactNode, type Ref } from 'react';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';
import type {  LatLngTuple, Map as LeafletMap } from 'leaflet';
import type { BBox } from '@/entities/area';
import { SelectArea } from '@/features/select-area';
import { DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM, OSM_TILE_URL } from '@/shared/config';
import styles from './MapView.module.css';

import {
  REGIONS_CONFIG,
  fetchRoadGraph,
  fetchOriginalPoints,
  RoadGraphLayer,
} from '@/entities/road-graph';
import type { LogisticsPoint } from '@/entities/road-graph';

interface MapViewProps {
  onNodeClick?: (nodeId: string) => void;
  mapRef?: Ref<LeafletMap>;
  center?: LatLngTuple;
  zoom?: number;
  children?: ReactNode;
  legend?: ReactNode;
  showRegions?: boolean;
  onAreaSelect?: (area: BBox | null) => void;
  point1?: string;
  point2?: string;
  setPoint1?: (value: string) => void;
  setPoint2?: (value: string) => void;
  bounds?: BBox;
}

interface RegionData {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  graph: any;
  points: LogisticsPoint[];
}

function FitBounds({ bounds }: { bounds: BBox }) {
  const map = useMap();

  useEffect(() => {
    map.fitBounds(
      [
        [bounds.minLat, bounds.minLng],
        [bounds.maxLat, bounds.maxLng],
      ],
      {
        padding: [40, 40],
        maxZoom: DEFAULT_MAP_ZOOM,
      }
    );
  }, [map, bounds.minLat, bounds.maxLat, bounds.minLng, bounds.maxLng]);

  return null;
}

export function MapView({
  mapRef,
  center = DEFAULT_MAP_CENTER,
  zoom = DEFAULT_MAP_ZOOM,
  bounds,
  children,
  legend,
  showRegions = false,
  onAreaSelect,
  point1 = '',
  point2 = '',
  setPoint1 = () => {},
  setPoint2 = () => {},
}: MapViewProps) {
  const [regionsData, setRegionsData] = useState<Record<string, RegionData>>({});

  useEffect(() => {
    if (!showRegions) return;
    REGIONS_CONFIG.forEach(async (region) => {
      const [graph, points] = await Promise.all([
        fetchRoadGraph(region.url),
        fetchOriginalPoints(region.pointsUrl),
      ]);

      setRegionsData((prev) => ({
        ...prev,
        [region.id]: { graph, points },
      }));
    });
  }, [showRegions]);

  return (
    <MapContainer
      ref={mapRef}
      center={center}
      zoom={zoom}
      className={styles.map}
      zoomControl={false}
    >
      <TileLayer url={OSM_TILE_URL} attribution="" />
      {bounds && <FitBounds bounds={bounds} />}

      {showRegions &&
        REGIONS_CONFIG.map((region) => {
          const data = regionsData[region.id];
          if (!data?.graph) return null;

          return (
            <RoadGraphLayer
              key={region.id}
              data={data.graph}
              regionColor={region.color}
              pointColor={region.pointColor}
              regionLabel={region.label}
            />
          );
        })}

      {legend && <div className={styles.legend}>{legend}</div>}

      {onAreaSelect && (
        <SelectArea
          onChange={onAreaSelect}
          point1={point1}
          point2={point2}
          setPoint1={setPoint1}
          setPoint2={setPoint2}
        />
      )}

      {children}
    </MapContainer>
  );
}
