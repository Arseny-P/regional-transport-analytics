import { useMemo, useState, type ReactNode } from 'react';
import type { LatLngTuple } from 'leaflet';
import type { BBox } from '@/entities/area';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { AppSidebar } from '@/widgets/app-layout';
import { MapView } from '@/widgets/map-view';
import { RegionBoundary, useRegion, useRegions } from '@/entities/region';
import { MetricSelect } from '@/features/select-metric';
import {
  GraphLayer,
  analysisErrorMessage,
  analysisRequestErrorMessage,
  GraphLegend,
  getGraphTransports,
  getNodeTransport,
  getNodeMetricRows,
  NodeCardOverlay,
  selectMetrics,
  isFinalState,
  METRIC_LABELS,
  REGION_METRIC_NAMES,
  NODE_METRIC_NAMES,
  formatMetricValue,
  useAnalysisJob,
  type GraphTransportMode,
  type JobState,
  type NodeSelection,
  NodeCard,
} from '@/entities/analysis';
import { ApiError } from '@/shared/api';
import styles from './ResultPage.module.css';
import { Button, Message, Spinner } from '@/shared/ui';

const STATUS_LABELS: Record<JobState, string> = {
  queued: 'В очереди',
  running: 'Выполняется',
  cancel_requested: 'Отмена запрошена',
  canceled: 'Отменено',
  completed: 'Завершено',
  failed: 'Ошибка',
};

const LAYER_LABELS: Record<GraphTransportMode, string> = {
  road: 'Автодороги',
  rail: 'Железные дороги',
};

function readSavedViewport(
  state: unknown,
  jobId: string
): { center: LatLngTuple; zoom: number } | undefined {
  const saved = state as { jobId?: unknown; center?: unknown; zoom?: unknown } | null;
  if (saved?.jobId !== jobId || !Array.isArray(saved.center) || saved.center.length !== 2) return;

  const [lat, lng] = saved.center;
  const { zoom } = saved;
  if (
    typeof lat !== 'number' ||
    typeof lng !== 'number' ||
    typeof zoom !== 'number' ||
    ![lat, lng, zoom].every(Number.isFinite)
  ) {
    return;
  }

  return { center: [lat, lng], zoom };
}

function readSavedBounds(state: unknown, jobId: string): BBox | undefined {
  const saved = state as { jobId?: unknown; bounds?: unknown } | null;

  if (saved?.jobId !== jobId || !saved.bounds || typeof saved.bounds !== 'object') {
    return;
  }

  const bounds = saved.bounds as Record<string, unknown>;
  const { minLat, maxLat, minLng, maxLng } = bounds;

  if (
    typeof minLat !== 'number' ||
    typeof maxLat !== 'number' ||
    typeof minLng !== 'number' ||
    typeof maxLng !== 'number' ||
    ![minLat, maxLat, minLng, maxLng].every(Number.isFinite) ||
    minLat > maxLat ||
    minLng > maxLng
  ) {
    return;
  }

  return { minLat, maxLat, minLng, maxLng };
}

function ResultLayout({ sidebar, children }: { sidebar: ReactNode; children?: ReactNode }) {
  const navigate = useNavigate();
  // const [preview, setPreview] = useState<'warehouse' | 'intersection' | null>('intersection');

  const sidebarContent = (
    <>
      <h3 className={styles.title}>Результаты анализа</h3>
      {sidebar}

      <Button className={styles.newAnalysisButton} onClick={() => navigate('/start')}>
        Новый анализ
      </Button>
    </>
  );

  return (
    <div className={styles.page}>
      <AppSidebar>{sidebarContent}</AppSidebar>
      <div className={styles.content}>{children}</div>
    </div>
  );
}

function JobResult({ jobId }: { jobId: string }) {
  const navigate = useNavigate();
  const { state } = useLocation();
  const viewport = readSavedViewport(state, jobId);
  const bounds = readSavedBounds(state, jobId);
  const { status, result, heartbeatFailure, resultFailure } = useAnalysisJob(jobId);

  const requestFailure =
    [heartbeatFailure, resultFailure].find((failure) => failure && !failure.retrying) ??
    heartbeatFailure ??
    resultFailure;

  const requestError = requestFailure?.error ?? null;
  const [searchParams] = useSearchParams();
  const { regions } = useRegions();
  const regionId =
    searchParams.get('region_id') ?? (regions?.length === 1 ? regions[0].region_id : null);
  const returnToArea = () =>
    navigate(regionId ? `/analysis?region_id=${encodeURIComponent(regionId)}` : '/start');
  const [metric, setMetric] = useState('');
  const [selection, setSelection] = useState<NodeSelection | null>(null);
  const [hiddenModes, setHiddenModes] = useState<GraphTransportMode[]>([]);

  const job = status ?? result;
  const failureMessage =
    job?.error && job.error.code !== 'analysis_canceled' ? analysisErrorMessage(job.error) : null;
  const graph = result?.graph;
  const modes = useMemo(() => (graph ? getGraphTransports(graph) : []), [graph]);
  const visibleModes = modes.filter((mode) => !hiddenModes.includes(mode));
  const visibleNodes =
    graph?.nodes.filter((node) => visibleModes.includes(getNodeTransport(node))) ?? [];
  const visibleNodeIds = new Set(visibleNodes.map(({ id }) => id));
  const hasGraph = !!graph?.nodes.length;
  const fallbackRegionId = viewport || hasGraph ? null : regionId;
  const { region: fallbackRegion } = useRegion(fallbackRegionId);
  const selectedNode =
    selection &&
    visibleNodes.find(
      (node) => node.id === selection.id && node.attributes?.object_type === selection.type
    );
  if (selection && !selectedNode) setSelection(null);

  const setLayerVisibility = (mode: GraphTransportMode, visible: boolean) => {
    setHiddenModes((current) =>
      visible ? current.filter((hidden) => hidden !== mode) : [...current, mode]
    );
    if (!visible && selectedNode && getNodeTransport(selectedNode) === mode) setSelection(null);
  };

  const { globalMetrics, metricsByNodeId } = selectMetrics(result?.metrics ?? []);
  const globalValues = new Map(globalMetrics.map(({ name, value }) => [name, value]));
  const hasRegionalMetrics = REGION_METRIC_NAMES.some((name) => globalValues.has(name));
  const [longitude, latitude] = selectedNode?.position ?? [];
  const popupPosition = useMemo<[number, number] | null>(
    () => (latitude === undefined || longitude === undefined ? null : [latitude, longitude]),
    [latitude, longitude]
  );
  const notFound = requestError instanceof ApiError && requestError.status === 404;
  const requestFailed = !!requestFailure && !requestFailure.retrying;
  const isFinal = !!job && isFinalState(job.status);
  const isWaiting = !requestFailed && !graph && (!isFinal || !result);
  const changeArea = <Button onClick={() => navigate('/start')}>Начать новый анализ</Button>;
  const cancelControl =
    job && !isFinal ? <Button onClick={returnToArea}>Отменить анализ</Button> : null;
  const waitingTitle = requestError
    ? 'Восстанавливаем соединение'
    : job?.status === 'queued'
      ? 'Анализ в очереди'
      : job?.status === 'cancel_requested'
        ? 'Ожидаем отмены анализа'
        : job?.status === 'running'
          ? 'Выполняется анализ'
          : 'Получаем состояние задачи';

  const sidebar = notFound ? (
    <p className={styles.error}>Задача не найдена. Запустите новый анализ.</p>
  ) : (
    <>
      <p
        className={styles.status}
        data-status={requestFailed ? 'failed' : job?.status}
        role="status"
      >
        Статус: {requestFailed ? 'Ошибка' : job ? STATUS_LABELS[job.status] : 'подключение...'}
      </p>
      {failureMessage && <p className={styles.error}>{failureMessage}</p>}
      {requestError && (
        <p className={styles.warning} role="alert">
          {analysisRequestErrorMessage(requestError)}
        </p>
      )}
      {job?.status === 'cancel_requested' && (
        <p role="status">Отмена запрошена. Ожидаем подтверждения сервера.</p>
      )}
      {!isWaiting && cancelControl}
      {job?.status === 'canceled' && hasGraph && (
        <p role="status">Анализ отменён. Доступен ранее построенный граф.</p>
      )}
      {graph && !graph.nodes.length && <p>Граф в выбранной области пуст.</p>}

      {modes.length > 0 && (
        <fieldset className={styles.layers}>
          <legend>Слои карты</legend>
          {modes.map((mode) => (
            <label key={mode}>
              <input
                type="checkbox"
                checked={visibleModes.includes(mode)}
                onChange={(event) => setLayerVisibility(mode, event.target.checked)}
              />
              {LAYER_LABELS[mode]}
            </label>
          ))}
        </fieldset>
      )}

      <MetricSelect
        names={NODE_METRIC_NAMES}
        metrics={[
          ...new Map(
            (result?.metrics ?? [])
              .filter(
                (m) =>
                  m.node_id !== undefined &&
                  visibleNodeIds.has(m.node_id) &&
                  NODE_METRIC_NAMES.some((name) => name === m.name)
              )
              .map((m) => [m.name, m])
          ).values(),
        ]}
        value={metric}
        onChange={setMetric}
      />
      {(!graph || modes.includes('road')) && (
        <>
          <h4>Показатели региона</h4>
          <table className={styles.metricsTable}>
            <thead>
              <tr>
                <th scope="col">Показатель</th>
                <th scope="col">Значение</th>
              </tr>
            </thead>
            <tbody>
              {REGION_METRIC_NAMES.map((name) => (
                <tr key={name}>
                  <th scope="row">{METRIC_LABELS[name] ?? name}</th>
                  <td>{formatMetricValue(name, globalValues.get(name))}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!hasRegionalMetrics && !isFinal && !requestFailed && (
            <p className={styles.muted}>
              {hasGraph
                ? 'Ожидаем значения метрик.'
                : 'Значения появятся после построения графа и расчёта метрик.'}
            </p>
          )}
        </>
      )}
    </>
  );

  return (
    <ResultLayout sidebar={sidebar}>
      <MapView
        center={viewport?.center}
        zoom={viewport?.zoom}
        bounds={bounds}
        showRegions={false}
        legend={
          visibleModes.length > 0 && (
            <GraphLegend
              colorBy={metric || undefined}
              nodes={visibleNodes}
              visibleModes={visibleModes}
              metrics={result?.metrics}
            />
          )
        }
      >
        {fallbackRegion && fallbackRegion.region_id === fallbackRegionId && (
          <RegionBoundary region={fallbackRegion} />
        )}
        {graph && (
          <GraphLayer
            metrics={result?.metrics ?? []}
            graph={graph}
            visibleModes={visibleModes}
            colorBy={metric || undefined}
            selection={selection}
            onNodeSelect={setSelection}
          />
        )}
        {selectedNode && popupPosition && (
          <NodeCardOverlay position={popupPosition}>
            <NodeCard
              node={{
                id: selectedNode.id,
                kind: selectedNode.attributes?.object_type,
                railKind: selectedNode.attributes?.node_kind,
                name: selectedNode.attributes?.name,
                connectionStatus: selectedNode.attributes?.is_isolated
                  ? (selectedNode.attributes.isolation_reason ?? 'Изолирован')
                  : undefined,
              }}
              metrics={getNodeMetricRows(selectedNode, metricsByNodeId.get(selectedNode.id) ?? [])}
              onClose={() => setSelection(null)}
            />
          </NodeCardOverlay>
        )}
      </MapView>
      {isWaiting && (
        <div className={styles.overlay}>
          <Message
            title={waitingTitle}
            description={
              requestError
                ? `${analysisRequestErrorMessage(requestError)} Повторяем запрос автоматически.`
                : job?.status === 'cancel_requested'
                  ? 'Запрос на отмену отправлен. Дождитесь подтверждения сервера.'
                  : 'Ожидаем готовности графа выбранной территории.'
            }
            icon={<Spinner size="large" text="" />}
            actions={cancelControl}
          />
        </div>
      )}
      {requestFailed && (
        <div className={styles.overlay}>
          <Message
            title={notFound ? 'Анализ не найден' : 'Не удалось получить результат'}
            description={analysisRequestErrorMessage(requestError)}
            actions={changeArea}
          />
        </div>
      )}
      {!requestFailed && isFinal && !!result && !hasGraph && (
        <div className={styles.overlay}>
          <Message
            title={
              job?.status === 'failed'
                ? 'Не удалось выполнить анализ'
                : job?.status === 'canceled'
                  ? 'Анализ отменён'
                  : 'Данные не найдены'
            }
            description={
              failureMessage ??
              (job?.status === 'failed'
                ? 'Не удалось завершить анализ. Попробуйте запустить его снова.'
                : job?.status === 'canceled'
                  ? 'Можно изменить параметры и запустить анализ снова.'
                  : 'В выбранной области не найдено объектов. Измените область или параметры анализа.')
            }
            actions={changeArea}
          />
        </div>
      )}
    </ResultLayout>
  );
}

export function ResultPage() {
  const [searchParams] = useSearchParams();
  const jobId = searchParams.get('job_id');

  if (!jobId) {
    return (
      <ResultLayout
        sidebar={<p className={styles.error}>Нет данных анализа. Запустите новый анализ.</p>}
      >
        <MapView showRegions={false} />
        <div className={styles.overlay}>
          <Message
            title="Нет данных анализа"
            description="Выберите область и запустите анализ, чтобы увидеть граф."
          />
        </div>
      </ResultLayout>
    );
  }

  return <JobResult key={jobId} jobId={jobId} />;
}
