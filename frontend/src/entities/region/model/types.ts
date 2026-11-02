import type { Position } from '@/shared/api';

export interface RegionSummary {
  region_id: string;
  name: string;
}

export type RegionList = RegionSummary[];

export type LinearRing = Position[];

export type PolygonCoordinates = LinearRing[];

export type BoundaryGeometry =
  | { type: 'Polygon'; coordinates: PolygonCoordinates }
  | { type: 'MultiPolygon'; coordinates: PolygonCoordinates[] };

export interface Region {
  region_id: string;
  boundary: BoundaryGeometry;
}

export interface RegionFeature {
  type: 'Feature';
  geometry: BoundaryGeometry;
  properties: Record<string, unknown> | null;
}

export interface RegionFeatureCollection {
  type: 'FeatureCollection';
  features: RegionFeature[];
}
