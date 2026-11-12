import { useEffect, useState, type ReactNode } from 'react';
import { MapContainer, TileLayer } from 'react-leaflet';
import type { LatLngTuple } from 'leaflet';
import type { BBox } from '@/entities/area';
import { SelectArea } from '@/features/select-area';
import { DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM, OSM_TILE_URL } from '@/shared/config';
import styles from './MapView.module.css';

import {
  REGIONS_CONFIG,
  fetchRoadGraph,
  fetchOriginalPoints,
  RoadGraphLayer,
  RoadGraphLegend
} from '@/entities/road-graph';
import type { LogisticsPoint } from '@/entities/road-graph';

interface MapViewProps {
  center?: LatLngTuple;
  zoom?: number;
  children?: ReactNode;
  onAreaSelect?: (area: BBox | null) => void;
  point1?: string;
  point2?: string;
  setPoint1?: (value: string) => void;
  setPoint2?: (value: string) => void;
}

interface RegionData {
  graph: any;
  points: LogisticsPoint[];
}

export function MapView({
  center = DEFAULT_MAP_CENTER,
  zoom = DEFAULT_MAP_ZOOM,
  children,
  onAreaSelect,
  point1 = '',
  point2 = '',
  setPoint1 = () => {},
  setPoint2 = () => {},
}: MapViewProps) {
  const [regionsData, setRegionsData] = useState<Record<string, RegionData>>({});

  useEffect(() => {
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
  }, []);

  return (
    <MapContainer 
      center={center} 
      zoom={zoom} 
      className={styles.map} 
      zoomControl={false}
    >
      <TileLayer url={OSM_TILE_URL} attribution="" />
      
      {REGIONS_CONFIG.map((region) => {
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
      
      <RoadGraphLegend />
      
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