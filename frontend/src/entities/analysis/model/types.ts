import type { Position } from '@/shared/api';

export const FINAL_JOB_STATES = ['completed', 'failed', 'canceled'] as const;

export type JobState =
  'queued' | 'running' | 'cancel_requested' | (typeof FINAL_JOB_STATES)[number];

export interface AnalysisFailure {
  code: string;
  message: string;
}

export interface AnalysisStatus {
  job_id: string;
  status: JobState;
  graph_available: boolean;
  metrics_available: boolean;
  error?: AnalysisFailure;
}

type Attributes = Record<string, unknown>;

export const GRAPH_TRANSPORT_MODES = ['road', 'rail'] as const;
export type GraphTransportMode = (typeof GRAPH_TRANSPORT_MODES)[number];
export type RailNodeKind = 'switch' | 'junction' | 'endpoint' | 'boundary';

export interface NodeSelection {
  id: string;
  type: 'warehouse' | 'intersection' | 'rail_node';
}

export interface GraphNode {
  id: string;
  position: Position;
  attributes?: Attributes & {
    object_type?: NodeSelection['type'] | 'road_node';
    transport_mode?: GraphTransportMode;
    node_kind?: RailNodeKind;
    physical_degree?: number;
    name?: string;
    is_isolated?: boolean;
    isolation_reason?: string;
  };
}

export interface GraphEdge {
  segment_id?: string;
  id: string;
  source: string;
  target: string;
  geometry?: Position[];
  attributes?: Attributes & {
    edge_type?: 'road' | 'access_connector';
    transport_mode?: GraphTransportMode;
    length_m?: number;
    oneway?: boolean;
    routes_count?: number;
  };
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Metric {
  node_id?: string;
  name: string;
  value: number;
}

export interface AnalysisResult extends AnalysisStatus {
  graph: Graph | null;
  metrics: Metric[];
}

export function isFinalState(state: JobState): boolean {
  return (FINAL_JOB_STATES as readonly JobState[]).includes(state);
}

export function selectMetrics(metrics: Metric[]) {
  const globalMetrics = metrics.filter((m) => m.node_id === undefined);
  const metricsByNodeId = new Map<string, Metric[]>();
  for (const m of metrics)
    if (m.node_id !== undefined)
      metricsByNodeId.set(m.node_id, [...(metricsByNodeId.get(m.node_id) ?? []), m]);
  return { globalMetrics, metricsByNodeId };
}
