import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '@/widgets/layout';
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

  const [latitude1 = '', longitude1 = ''] = point1.split(',');
  const [latitude2 = '', longitude2 = ''] = point2.split(',');

  const navigateToResult = () => navigate('/result');

  const sidebarContent = (
    <>
      <h3 className={styles.title}>Ввод координат</h3>
      <div className={styles.coordinates}>
        <h4>Точка 1</h4>

        <label>
          широта
          <input
            type="text"
            placeholder="59.88"
            value={latitude1}
            onChange={(e) =>
              setPoint1(`${e.target.value},${longitude1}`)
            }
            className={styles.input}
          />
        </label>

        <label>
          долгота
          <input
            type="text"
            placeholder="29.82"
            value={longitude1}
            onChange={(e) =>
              setPoint1(`${latitude1},${e.target.value}`)
            }
            className={styles.input}
          />
        </label>
      </div>

      <div className={styles.coordinates}>
        <h4>Точка 2</h4>

        <label>
          широта
          <input
            type="text"
            placeholder="59.89"
            value={latitude2}
            onChange={(e) =>
              setPoint2(`${e.target.value},${longitude2}`)
            }
            className={styles.input}
          />
        </label>

        <label>
          долгота
          <input
            type="text"
            placeholder="29.83"
            value={longitude2}
            onChange={(e) =>
              setPoint2(`${latitude2},${e.target.value}`)
            }
            className={styles.input}
          />
        </label>
      </div>

      <div className={styles.transports}>
        <h3 className={styles.transportsTitle}>Виды транспорта:</h3>
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
      <Layout sidebarContent={sidebarContent}>
        <MapView>
          <SelectArea
            onChange={setSelectedArea}
            point1={point1}
            point2={point2}
            setPoint1={setPoint1}
            setPoint2={setPoint2}
          />
        </MapView>
      </Layout>

      <div className={styles.actions}>
        <span className={styles.hint}>{hint}</span>
        {error && <span className={styles.error}>{error}</span>}
        {/* <button
          onClick={() => selectedArea && run(selectedArea, transports)}
          disabled={!selectedArea || !transports.length || isLoading}
          className={styles.runButton}
        >
          {isLoading ? 'Запуск анализа...' : 'Начать анализ'}
        </button> */}
        <button onClick= {navigateToResult} 
        className={styles.newAnalysisButton}>
          Анализ
        </button>
      </div>

    
    </div>
  );
}
