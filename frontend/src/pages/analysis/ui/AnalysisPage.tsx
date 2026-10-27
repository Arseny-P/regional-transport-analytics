import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AppSidebar } from '@/widgets/app-layout';
import { MapView } from '@/widgets/map-view';
import { useRunAnalysis } from '@/features/run-analysis';
import { SelectArea } from '@/features/select-area';
import type { BBox } from '@/entities/area';
import {
  DEFAULT_TRANSPORT_MODES,
  TRANSPORT_MODES,
  TRANSPORT_MODE_LABELS,
  type TransportMode,
} from '@/entities/transport-mode';
import styles from './AnalysisPage.module.css';

export function AnalysisPage() {
  const navigate = useNavigate();
  const [selectedArea, setSelectedArea] = useState<BBox | null>(null);
  const [point1, setPoint1] = useState('');
  const [point2, setPoint2] = useState('');
  const [transports, setTransports] = useState<TransportMode[]>(DEFAULT_TRANSPORT_MODES);
  const { run, isLoading, error } = useRunAnalysis((jobId) =>
    navigate(`/result?job_id=${encodeURIComponent(jobId)}`)
  );

  const toggleTransport = (mode: TransportMode) =>
    setTransports((current) =>
      current.includes(mode) ? current.filter((m) => m !== mode) : [...current, mode]
    );

  const sidebarContent = (
    <>
      <h3 className={styles.title}>Ввод координат</h3>
      <label>
        Точка 1 (lat,lng):
        <input
          type="text"
          placeholder="59.88,29.82"
          value={point1}
          onChange={(e) => setPoint1(e.target.value)}
          className={styles.input}
        />
      </label>
      <label>
        Точка 2 (lat,lng):
        <input
          type="text"
          placeholder="59.88,29.83"
          value={point2}
          onChange={(e) => setPoint2(e.target.value)}
          className={styles.input}
        />
      </label>

      <div className={styles.transports}>
        <h4 className={styles.transportsTitle}>Виды транспорта:</h4>
        {TRANSPORT_MODES.map((mode) => (
          <label key={mode} className={styles.transport}>
            <input
              type="checkbox"
              checked={transports.includes(mode)}
              onChange={() => toggleTransport(mode)}
            />{' '}
            {TRANSPORT_MODE_LABELS[mode]}
          </label>
        ))}
      </div>
    </>
  );

  const hint = !selectedArea
    ? 'Выделите участок карты двумя кликами'
    : !transports.length
      ? 'Выберите хотя бы один вид транспорта'
      : 'Область выбрана';

  return (
    <div className={styles.page}>
      <AppSidebar>{sidebarContent}</AppSidebar>
      <MapView>
        <SelectArea
          onChange={setSelectedArea}
          point1={point1}
          point2={point2}
          setPoint1={setPoint1}
          setPoint2={setPoint2}
        />
      </MapView>

      <div className={styles.actions}>
        <span className={styles.hint}>{hint}</span>
        {error && <span className={styles.error}>{error}</span>}
        <button
          onClick={() => selectedArea && run(selectedArea, transports)}
          disabled={!selectedArea || !transports.length || isLoading}
          className={styles.runButton}
        >
          {isLoading ? 'Запуск анализа...' : 'Начать анализ'}
        </button>
      </div>
    </div>
  );
}
