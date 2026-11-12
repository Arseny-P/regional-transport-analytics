import type { Feature, FeatureCollection, Point, LineString } from 'geojson';

export interface LogisticsPoint {
  name: string;
  lat: number;
  lon: number;
  type: string;
}

export type RoadGraphData = FeatureCollection<Point | LineString>;

export interface OpenApiNode {
  id: string;
  lat: number;
  lon: number;
  name?: string;
  type?: string;
  properties?: Record<string, unknown>;
}

export interface OpenApiEdge {
  id?: string;
  from: string;
  to: string;
  geometry?: [number, number][]; 
  type?: string;
  distance?: number;
  properties?: Record<string, unknown>;
}

export interface OpenApiGraph {
  nodes: OpenApiNode[];
  edges: OpenApiEdge[];
}

export type NodeProperties = {
  kind: 'node';
  id: string;
  name: string;
  type: string;
};

export type EdgeProperties = {
  kind: 'edge';
  id?: string;
  from: string;
  to: string;
  type: string;
  distance?: number;
};

export type RoadGraphFeature =
  | Feature<Point, NodeProperties>
  | Feature<LineString, EdgeProperties>;