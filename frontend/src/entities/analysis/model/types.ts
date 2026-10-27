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

export interface GraphNode {
  id: string;
  position: Position;
  attributes?: Attributes;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  geometry?: Position[];
  attributes?: Attributes;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Metric {
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
