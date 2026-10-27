import { useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AppSidebar } from '@/widgets/app-layout';
import { MapView } from '@/widgets/map-view';
import { MetricSelect } from '@/features/select-metric';
import { GraphLayer, isFinalState, useAnalysisJob, type JobState } from '@/entities/analysis';
import { ApiError } from '@/shared/api';
import styles from './ResultPage.module.css';

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
      <button onClick={() => navigate('/analysis')} className={styles.newAnalysisButton}>
        Новый анализ
      </button>
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
  const { status, result, requestError } = useAnalysisJob(jobId);
  const [metric, setMetric] = useState('');

  const job = status ?? result;
  const graph = result?.graph;
  const notFound = requestError instanceof ApiError && requestError.status === 404;
  const isFinal = !!job && isFinalState(job.status);
  const isWaiting = !notFound && !graph && !isFinal;

  const sidebar = notFound ? (
    <p className={styles.error}>Задача не найдена. Запустите новый анализ.</p>
  ) : (
    <>
      <p>Статус: {job ? STATUS_LABELS[job.status] : 'подключение...'}</p>
      {job?.error && <p className={styles.error}>{job.error.message}</p>}
      {requestError && <p className={styles.warning}>Нет связи с сервером, повторяем запрос...</p>}
      {graph && !graph.nodes.length && <p>Граф в выбранной области пуст.</p>}

      <h4>Метрика графа:</h4>
      {result?.metrics.length ? (
        <MetricSelect metrics={result.metrics} value={metric} onChange={setMetric} />
      ) : (
        <p className={styles.muted}>
          {isFinal ? 'Метрики не рассчитаны.' : 'Метрики рассчитываются...'}
        </p>
      )}
    </>
  );

  return (
    <ResultLayout sidebar={sidebar}>
      <MapView>{graph && <GraphLayer graph={graph} colorBy={metric || undefined} />}</MapView>
      {isWaiting && (
        <div className={styles.overlay}>
          <div className={styles.spinner} />
          <span className={styles.overlayText}>Строим граф...</span>
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
      />
    );
  }

  return <JobResult key={jobId} jobId={jobId} />;
}
