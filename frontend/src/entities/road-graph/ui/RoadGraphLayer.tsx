import { GeoJSON } from 'react-leaflet';
import * as L from 'leaflet';
import type { Feature, FeatureCollection, Point, LineString } from 'geojson';

interface RoadGraphLayerProps {
  data: FeatureCollection<Point | LineString> | null;
  regionColor: string;
  pointColor: string;
  regionLabel: string;
}

export function RoadGraphLayer({ data, regionColor, pointColor, regionLabel }: RoadGraphLayerProps) {
  if (!data) return null;

  return (
    <GeoJSON
      data={data}
      style={(feature) => {
        if (feature?.geometry?.type === 'LineString' || feature?.properties?.kind === 'edge') {
          return { color: regionColor, weight: 3, opacity: 0.7 };
        }
        return {};
      }}
      pointToLayer={(feature, latlng) => {
        if (feature?.geometry?.type === 'Point' || feature?.properties?.kind === 'node') {
          const name = feature.properties?.name ?? 'Объект';
          return L.circleMarker(latlng, {
            radius: 8,
            fillColor: pointColor, 
            color: '#ffffff',
            weight: 2,
            fillOpacity: 0.9,
          }).bindPopup(`<b>${name}</b><br/><small>(${regionLabel})</small>`);
        }
        return L.marker(latlng);
      }}
    />
  );
}