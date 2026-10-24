export type BBoxTuple = [west: number, south: number, east: number, north: number];

export type QueryParams = Record<string, string | number | boolean | undefined>;

export interface ApiErrorBody {
  detail?: string | { msg: string }[];
}

export interface MstEdgeDto {
  from_index: number;
  to_index: number;
  distance: number;
}

export interface LogisticsPointDto {
  lat: number;
  lon: number;
  tags: Record<string, unknown>;
  mode?: string;
}

export interface AnalyzeResponseDto {
  status: 'ok';
  mode: string;
  bbox: BBoxTuple;
  map_path: string;
  coords_path: string;
  mst_path: string;
  points: LogisticsPointDto[];
  edges: MstEdgeDto[];
  total_distance: number;
  nodes_count: number;
  edges_count: number;
}

export interface MetricsResponseDto {
  status: 'ok';
  metric: string;
  map_path: string;
}
