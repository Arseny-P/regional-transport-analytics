import type { Metric } from '@/entities/analysis';
import styles from './MetricSelect.module.css';

interface MetricSelectProps {
  metrics: Metric[];
  value: string;
  onChange: (name: string) => void;
}

export function MetricSelect({ metrics, value, onChange }: MetricSelectProps) {
  const selected = metrics.find((metric) => metric.name === value);

  return (
    <div className={styles.root}>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={styles.select}>
        <option value="">Выберите метрику</option>
        {metrics.map((metric) => (
          <option key={metric.name} value={metric.name}>
            {metric.name}
          </option>
        ))}
      </select>
      {selected && (
        <div>
          Значение: <b>{selected.value}</b>
        </div>
      )}
    </div>
  );
}
