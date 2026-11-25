import { useMemo, useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AppSidebar } from '@/widgets/app-layout';
import { MapView } from '@/widgets/map-view';
import { MetricSelect } from '@/features/select-metric';
import {
  GraphLayer,
  getNodeMetricRows,
  NodeCardOverlay,
  selectMetrics,
  isFinalState,
  METRIC_LABELS,
  useAnalysisJob,
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

function ResultLayout({ sidebar, children }: { sidebar: ReactNode; children?: ReactNode }) {
  const navigate = useNavigate();
  // const [preview, setPreview] = useState<'warehouse' | 'intersection' | null>('intersection');

  const sidebarContent = (
    <>
      <h3 className={styles.title}>Результаты анализа</h3>
      {sidebar}

      <Button className={styles.newAnalysisButton} onClick={() => navigate('/analysis')}>
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
  const { status, result, requestError } = useAnalysisJob(jobId);
  const [metric, setMetric] = useState('');
  const [selection, setSelection] = useState<NodeSelection | null>(null);

  const job = status ?? result;
  const graph = result?.graph;
  const selectedNode =
    selection &&
    graph?.nodes.find(
      (node) => node.id === selection.id && node.attributes?.object_type === selection.type
    );
  if (selection && !selectedNode) setSelection(null);

  const { globalMetrics, metricsByNodeId } = selectMetrics(result?.metrics ?? []);
  const [longitude, latitude] = selectedNode?.position ?? [];
  const popupPosition = useMemo<[number, number] | null>(
    () => (latitude === undefined || longitude === undefined ? null : [latitude, longitude]),
    [latitude, longitude]
  );
  const notFound = requestError instanceof ApiError && requestError.status === 404;
  const isFinal = !!job && isFinalState(job.status);
  const isWaiting = !notFound && !graph && (!isFinal || !result);
  const hasGraph = !!graph?.nodes.length;
  const changeArea = (
    <Button onClick={() => navigate('/analysis')}>Изменить область или параметры</Button>
  );
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
      <p className={styles.status} data-status={job?.status} role="status">
        Статус: {job ? STATUS_LABELS[job.status] : 'подключение...'}
      </p>
      {job?.error && <p className={styles.error}>{job.error.message}</p>}
      {requestError && <p className={styles.warning}>Нет связи с сервером, повторяем запрос...</p>}
      {graph && !graph.nodes.length && <p>Граф в выбранной области пуст.</p>}

      <MetricSelect
        metrics={[
          ...new Map(
            (result?.metrics ?? []).filter((m) => m.node_id !== undefined).map((m) => [m.name, m])
          ).values(),
        ]}
        value={metric}
        onChange={setMetric}
      />
      <h4>Простые метрики графа:</h4>
      {globalMetrics.length ? (
        <>
          <table className={styles.metricsTable}>
            <thead>
              <tr>
                <th scope="col">Показатель</th>
                <th scope="col">Значение</th>
              </tr>
            </thead>
            <tbody>
              {' '}
              {globalMetrics.map(({ name, value }) => (
                <tr key={name}>
                  <th scope="row">{METRIC_LABELS[name] ?? name}</th>
                  <td>{value ?? 'Не рассчитано'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <p className={styles.muted}>
          {isFinal
            ? 'Метрики не рассчитаны.'
            : hasGraph
              ? 'Метрики рассчитываются...'
              : 'Метрики будут доступны после построения графа.'}
        </p>
      )}
    </>
  );

  return (
    <ResultLayout sidebar={sidebar}>
      <MapView>
        {graph && (
          <GraphLayer
            metrics={result?.metrics ?? []}
            graph={graph}
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
                ? 'Нет связи с сервером. Повторяем запрос автоматически.'
                : 'Ожидаем готовности графа выбранной территории.'
            }
            icon={<Spinner size="large" text="" />}
          />
        </div>
      )}
      {notFound && (
        <div className={styles.overlay}>
          <Message
            title="Задача не найдена"
            description="Запустите новый анализ выбранной области."
            actions={changeArea}
          />
        </div>
      )}
      {!notFound && isFinal && !!result && !hasGraph && (
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
              job?.error?.message ??
              (job?.status === 'canceled'
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
        <MapView />
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
