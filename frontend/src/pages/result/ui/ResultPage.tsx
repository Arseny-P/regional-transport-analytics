import { useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AppSidebar } from '@/widgets/app-layout';
import { MapView } from '@/widgets/map-view';
import { MetricSelect } from '@/features/select-metric';
import { GraphLayer, isFinalState, useAnalysisJob, type JobState } from '@/entities/analysis';
import { ApiError } from '@/shared/api';
import styles from './ResultPage.module.css';
import { Button, Message, Spinner} from '@/shared/ui';

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

  const job = status ?? result;
  const graph = result?.graph;
  const notFound = requestError instanceof ApiError && requestError.status === 404;
  const isFinal = !!job && isFinalState(job.status);
  const isWaiting = !notFound && !graph && !isFinal;
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
      <p className={styles.status} data-status={job?.status} role="status">Статус: {job ? STATUS_LABELS[job.status] : 'подключение...'}</p>
      {job?.error && <p className={styles.error}>{job.error.message}</p>}
      {requestError && <p className={styles.warning}>Нет связи с сервером, повторяем запрос...</p>}
      {graph && !graph.nodes.length && <p>Граф в выбранной области пуст.</p>}

      <h4>Метрика графа:</h4>
      {result?.metrics.length ? (
        <MetricSelect metrics={result.metrics} value={metric} onChange={setMetric} />
      ) : (
        <p className={styles.muted}>
          {isFinal ? 'Метрики не рассчитаны.' : hasGraph ? 'Метрики рассчитываются...' : 'Метрики будут доступны после построения графа.'}
        </p>
      )}
    </>
  );

  return (
    <ResultLayout sidebar={sidebar}>
      <MapView>{graph && <GraphLayer graph={graph} colorBy={metric || undefined} />}</MapView>
      {isWaiting && (
        <div className={styles.overlay}>
          <Message
            title={waitingTitle}
            description={requestError
              ? 'Нет связи с сервером. Повторяем запрос автоматически.'
              : 'Ожидаем готовности графа выбранной территории.'}
            icon={<Spinner size="large" text="" />}
          />
        </div>
      )}
      {notFound && (
        <div className={styles.overlay}>
          <Message title="Задача не найдена" description="Запустите новый анализ выбранной области." actions={changeArea} />
        </div>
      )}
      {!notFound && isFinal && !hasGraph && (
        <div className={styles.overlay}>
          <Message
            title={job?.status === 'failed'
              ? 'Не удалось выполнить анализ'
              : job?.status === 'canceled'
                ? 'Анализ отменён'
                : 'Данные не найдены'}
            description={job?.error?.message ?? (
              job?.status === 'canceled'
                ? 'Можно изменить параметры и запустить анализ снова.'
                : 'В выбранной области не найдено объектов. Измените область или параметры анализа.'
            )}
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
          <Message title="Нет данных анализа" description="Выберите область и запустите анализ, чтобы увидеть граф." />
        </div>
      </ResultLayout>
    );
  }

  return <JobResult key={jobId} jobId={jobId} />;
}


