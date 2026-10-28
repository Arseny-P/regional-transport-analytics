import { http, HttpResponse } from 'msw';
import type { AnalysisStatus, Graph, Metric } from '@/entities/analysis';
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
  params: string;
  transports: string[];
  createdAt: number;
  lastSeenAt: number;
  canceled: boolean;
  graph: Graph;
}

const STORAGE_KEY = 'mock-analysis-jobs';
const QUEUE_MS = 1000;
const GRAPH_MS = 3000;
const METRICS_MS = 8000;
const HEARTBEAT_TIMEOUT_MS = 10000;
const MAX_AREA_SPAN = 1;
const NODES_COUNT = 15;

const loadJobs = (): Record<string, MockJob> =>
  JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}');
const saveJobs = (jobs: Record<string, MockJob>) =>
  localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));

const error = (status: number, code: string, message: string) =>
  HttpResponse.json({ code, message }, { status });

function buildGraph({ first_point, second_point }: AnalysisBody['area']): Graph {
  const random = (a: number, b: number) => a + Math.random() * (b - a);
  const nodes = Array.from({ length: NODES_COUNT }, (_, i) => ({
    id: String(i),
    position: [
      random(first_point.longitude, second_point.longitude),
      random(first_point.latitude, second_point.latitude),
    ] as [number, number],
    attributes: { degree: 0 },
  }));
  const edges = nodes.slice(1).map((node, i) => ({
    id: String(i),
    source: String(Math.floor(Math.random() * (i + 1))),
    target: node.id,
  }));
  for (const edge of edges) {
    nodes[Number(edge.source)].attributes.degree++;
    nodes[Number(edge.target)].attributes.degree++;
  }
  return { nodes, edges };
}

function metricsOf(graph: Graph): Metric[] {
  return [
    { name: 'vertex_count', value: graph.nodes.length },
    { name: 'edge_count', value: graph.edges.length },
    { name: 'degree', value: (2 * graph.edges.length) / graph.nodes.length },
  ];
}

function statusOf(jobId: string, job: MockJob): AnalysisStatus {
  const elapsed = Date.now() - job.createdAt;
  const graphReady = elapsed >= GRAPH_MS;
  const base = { job_id: jobId, graph_available: graphReady, metrics_available: false };

  if (job.canceled) return { ...base, status: 'canceled' };
  if (elapsed < METRICS_MS) return { ...base, status: elapsed < QUEUE_MS ? 'queued' : 'running' };
  if (job.transports.join() === 'sea') {
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
  http.post(`${API_URL}/analysis`, async ({ request }) => {
    const jobId = new URL(request.url).searchParams.get('job_id');
    if (!jobId) return error(400, 'bad_request', 'Не передан job_id.');

    const body = (await request.json()) as AnalysisBody;
    const { first_point, second_point } = body.area;
    if (!body.transports.length) return error(422, 'validation_error', 'Не выбран вид транспорта.');
    if (
      Math.abs(first_point.latitude - second_point.latitude) > MAX_AREA_SPAN ||
      Math.abs(first_point.longitude - second_point.longitude) > MAX_AREA_SPAN
    ) {
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

  http.post(`${API_URL}/analysis/heartbeat`, ({ request }) => {
    const { jobId, jobs, job } = findJob(request);
    if (!job) return error(404, 'job_not_found', 'Задача не найдена.');

    const now = Date.now();
    if (now - job.lastSeenAt > HEARTBEAT_TIMEOUT_MS && now - job.createdAt < METRICS_MS) {
      job.canceled = true;
    }
    job.lastSeenAt = now;
    saveJobs(jobs);
    return HttpResponse.json(statusOf(jobId, job));
  }),

  http.get(`${API_URL}/analysis/result`, ({ request }) => {
    const { jobId, job } = findJob(request);
    if (!job) return error(404, 'job_not_found', 'Задача не найдена.');

    const status = statusOf(jobId, job);
    return HttpResponse.json({
      ...status,
      graph: status.graph_available ? job.graph : null,
      metrics: status.metrics_available ? metricsOf(job.graph) : [],
    });
  }),
];
