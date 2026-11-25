import { METRIC_LABELS, type Metric } from '@/entities/analysis';
import styles from './MetricSelect.module.css';

interface MetricSelectProps {
  metrics: Metric[];
  names?: readonly string[];
  value: string;
  onChange: (name: string) => void;
}

export function MetricSelect({ metrics, names, value, onChange }: MetricSelectProps) {
  const options = names ?? metrics.map((metric) => metric.name);
  return (
    <div className={styles.root}>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={styles.select}>
        <option value="">Выберите метрику</option>
        {options.map((name) => {
          const available = metrics.some(
            (metric) => metric.name === name && Number.isFinite(metric.value)
          );
          return (
            <option key={name} value={name} disabled={!available}>
              {METRIC_LABELS[name] ?? name}
              {available ? '' : ' — не подключено'}
            </option>
          );
        })}
      </select>
    </div>
  );
}
