import { http, HttpResponse, delay } from 'msw';
import type { AnalysisStatus, Graph, Metric } from '@/entities/analysis';
import type { Region, RegionSummary } from '@/entities/region';
import type { Position } from '@/shared/api';
import { API_URL } from '@/shared/config';

interface MapPoint {
  latitude: number;
  longitude: number;
}

interface AnalysisBody {
  region_id: string;
  area: { first_point: MapPoint; second_point: MapPoint };
  transports: string[];
}

interface MockJob {
  scenario: string;
  resultAttempts?: number;
  params: string;
  transports: string[];
  createdAt: number;
  lastSeenAt: number;
  canceled: boolean;
  graph: Graph;
}

interface MockRegion extends RegionSummary {
  bounds: [minLng: number, minLat: number, maxLng: number, maxLat: number];
}

const REGIONS: MockRegion[] = [
  { region_id: 'region-001', name: 'spb.geojson', bounds: [29.4, 59.6, 30.8, 60.25] },
  { region_id: 'region-002', name: 'leningrad-region.geojson', bounds: [27.7, 58.4, 35.7, 61.3] },
];

const findRegion = (regionId: unknown) => REGIONS.find((r) => r.region_id === regionId);

function regionOf({ region_id, bounds: [minLng, minLat, maxLng, maxLat] }: MockRegion): Region {
  const ring: Position[] = [
    [minLng, minLat],
    [maxLng, minLat],
    [maxLng, maxLat],
    [minLng, maxLat],
    [minLng, minLat],
  ];
  return { region_id, boundary: { type: 'Polygon', coordinates: [ring] } };
}

function isInside({ bounds: [minLng, minLat, maxLng, maxLat] }: MockRegion, point: MapPoint) {
  return (
    point.longitude >= minLng &&
    point.longitude <= maxLng &&
    point.latitude >= minLat &&
    point.latitude <= maxLat
  );
}

const STORAGE_KEY = 'mock-analysis-jobs';
const QUEUE_MS = 1000;
const GRAPH_MS = 3000;
const METRICS_MS = 25000;
const HEARTBEAT_TIMEOUT_MS = 10000;
const NODES_COUNT = 15;

const loadJobs = (): Record<string, MockJob> =>
  JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}');
const saveJobs = (jobs: Record<string, MockJob>) =>
  localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));

const error = (status: number, code: string, message: string) =>
  HttpResponse.json({ code, message }, { status });

function buildGraph({ first_point, second_point }: AnalysisBody['area']): Graph {
  const nodes: Graph['nodes'] = Array.from({ length: NODES_COUNT }, (_, i) => ({
    id: String(i),
    position: [
      first_point.longitude +
        (second_point.longitude - first_point.longitude) * (0.1 + (i % 5) * 0.2),
      first_point.latitude +
        (second_point.latitude - first_point.latitude) * (0.1 + Math.floor(i / 5) * 0.35),
    ] as [number, number],
    attributes: {
      is_isolated: i === NODES_COUNT - 1,
      name: `Node ${i}`,
      degree: 0,
      object_type: i === 0 || i === NODES_COUNT - 1 ? 'warehouse' : i % 3 === 0 ? 'intersection' : 'road_node',
    },
  }));
  const edges: Graph['edges'] = nodes.slice(1, -1).flatMap((node, i) => [
    {
      id: String(i),
      source: String(i),
      target: node.id,
      segment_id: i === 0 ? undefined : `segment-${i}`,
      geometry: [nodes[i].position, node.position],
      attributes: { edge_type: i === 0 ? 'access_connector' : 'road', oneway: false },
    },
    {
      id: `reverse-${i}`,
      source: node.id,
      target: String(i),
      segment_id: i === 0 ? undefined : `segment-${i}`,
      geometry: [node.position, nodes[i].position],
      attributes: { edge_type: i === 0 ? 'access_connector' : 'road', oneway: false },
    },
  ]);

  return { nodes, edges };
}

function metricsOf(graph: Graph): Metric[] {
  return [
    ...graph.nodes.map((node, index) => ({ node_id: node.id, name: 'degree', value: index % 4 })),
    { name: 'vertex_count', value: graph.nodes.length },
    { name: 'edge_count', value: graph.edges.length },
    { name: 'degree', value: (2 * graph.edges.length) / graph.nodes.length },
  ];
}

function statusOf(jobId: string, job: MockJob): AnalysisStatus {
  const elapsed = Date.now() - job.createdAt;
  const graphReady = elapsed >= GRAPH_MS;
  const base = { job_id: jobId, graph_available: graphReady, metrics_available: false };

  if (job.scenario === 'canceled' && elapsed >= METRICS_MS)
    return { ...base, status: elapsed < METRICS_MS + 5000 ? 'cancel_requested' : 'canceled' };
  if (job.canceled) return { ...base, status: 'canceled' };
  if (elapsed < METRICS_MS) return { ...base, status: elapsed < QUEUE_MS ? 'queued' : 'running' };
  if (job.scenario === 'failed') {
    return {
      ...base,
      status: 'failed',
      error: { code: 'metrics_calculation_failed', message: 'Не удалось рассчитать метрики.' },
    };
  }
  return { ...base, status: 'completed', metrics_available: true };
}

function findJob(request: Request) {
  const jobId = new URL(request.url).searchParams.get('job_id') ?? '';
  const jobs = loadJobs();
  return { jobId, jobs, job: jobs[jobId] };
}

export const handlers = [
  http.get(`${API_URL}/regions`, () =>
    HttpResponse.json(REGIONS.map(({ region_id, name }) => ({ region_id, name })))
  ),

  http.get(`${API_URL}/regions/:regionId`, ({ params }) => {
    const region = findRegion(params.regionId);
    if (!region) return error(404, 'region_not_found', 'Регион не найден.');
    return HttpResponse.json(regionOf(region));
  }),

  http.post(`${API_URL}/analysis`, async ({ request }) => {
    const jobId = new URL(request.url).searchParams.get('job_id');
    if (!jobId) return error(400, 'bad_request', 'Не передан job_id.');

    const body = (await request.json()) as AnalysisBody;
    const { first_point, second_point } = body.area;
    const region = findRegion(body.region_id);
    if (!region) return error(404, 'region_not_found', 'Регион не найден.');
    if (!body.transports.length) return error(422, 'validation_error', 'Не выбран вид транспорта.');
    if (!isInside(region, first_point) || !isInside(region, second_point)) {
      return error(422, 'area_outside_region', 'Выделенная область выходит за границу региона.');
    }

    const jobs = loadJobs();
    const params = JSON.stringify(body);
    const existing = jobs[jobId];
    if (existing && existing.params !== params) {
      return error(409, 'job_parameters_conflict', 'Этот job_id уже используется.');
    }
    if (existing) return HttpResponse.json(statusOf(jobId, existing));

    const now = Date.now();
    jobs[jobId] = {
      scenario: import.meta.env.VITE_ANALYSIS_MOCK_SCENARIO ?? 'completed',
      params,
      transports: body.transports,
      createdAt: now,
      lastSeenAt: now,
      canceled: false,
      graph: buildGraph(body.area),
    };
    saveJobs(jobs);
    return HttpResponse.json({ job_id: jobId, status: 'queued' }, { status: 202 });
  }),

  http.post(`${API_URL}/analysis/heartbeat`, async ({ request }) => {
    const { jobId, jobs, job } = findJob(request);
    if (!job) return error(404, 'job_not_found', 'Задача не найдена.');

    const now = Date.now();
    if (now - job.lastSeenAt > HEARTBEAT_TIMEOUT_MS && now - job.createdAt < METRICS_MS) {
      job.canceled = true;
    }
    job.lastSeenAt = now;
    saveJobs(jobs);
    const snapshot = statusOf(jobId, job);
    if (job.scenario === 'slow-heartbeat') await delay(12000);
    return HttpResponse.json(snapshot);
  }),

  http.get(`${API_URL}/analysis/result`, async ({ request }) => {
    const { jobId, job, jobs } = findJob(request);
    if (!job) return error(404, 'job_not_found', 'Задача не найдена.');

    const status = statusOf(jobId, job);
    if (
      job.scenario === 'retry-final-result' &&
      status.status === 'completed' &&
      !job.resultAttempts
    ) {
      job.resultAttempts = 1;
      saveJobs(jobs);
      return error(500, 'temporary_error', 'Retry result');
    }
    if (job.scenario === 'slow-result') await delay(12000);
    return HttpResponse.json({
      ...status,
      graph: status.graph_available
        ? job.scenario === 'empty-graph'
          ? { nodes: [], edges: [] }
          : job.graph
        : null,
      metrics:
        status.metrics_available &&
        job.scenario !== 'empty-metrics' &&
        job.scenario !== 'empty-graph'
          ? metricsOf(job.graph)
          : [],
    });
  }),
];
