import { METRIC_LABELS, METRIC_DESCRIPTIONS, formatMetricValue } from '../config/metricLabels';
import { nodeMetricScale } from '../lib/nodeColor';
import type { Graph, Metric } from '../model/types';
import styles from './GraphLegend.module.css';

interface GraphLegendProps {
  colorBy?: string;
  graph?: Graph | null;
  metrics?: readonly Metric[];
}

export function GraphLegend({ colorBy, graph, metrics = [] }: GraphLegendProps) {
  const { min, max } = nodeMetricScale(graph?.nodes ?? [], metrics, colorBy);
  const hasValues = Number.isFinite(min) && Number.isFinite(max);
  return (
    <section className={styles.legend} aria-label="Легенда графа">
      <h4 className={styles.title}>Легенда</h4>
      <ul className={styles.items}>
        <li className={styles.row}>
          <span className={styles.warehouse} aria-hidden="true" />
          <span>Склады</span>
        </li>
        <li className={styles.row}>
          <span className={styles.intersection} aria-hidden="true" />
          <span>Перекрёстки</span>
        </li>
        <li className={styles.row}>
          <span className={styles.road} aria-hidden="true" />
          <span>Участки маршрутов</span>
        </li>
        <li className={styles.row}>
          <span className={styles.selected} aria-hidden="true" />
          <span>Выбранная вершина</span>
        </li>
      </ul>
      {colorBy && (
        <div className={styles.metric}>
          <h4 className={styles.title}>{METRIC_LABELS[colorBy] ?? colorBy}</h4>
          <p className={styles.description}>{METRIC_DESCRIPTIONS[colorBy]}</p>
          {hasValues ? (
            min === max ? (
              <p className={styles.equalValue}>
                <span className={styles.equalColor} aria-hidden="true" />
                Все значения одинаковы: {formatMetricValue(colorBy, min)}
              </p>
            ) : (
              <>
                <div className={styles.gradient} aria-hidden="true" />
                <div className={styles.range}>
                  <span>{formatMetricValue(colorBy, min)}</span>
                  <span>{formatMetricValue(colorBy, max)}</span>
                </div>
              </>
            )
          ) : (
            <p className={styles.note}>Значения выбранной метрики не подключены.</p>
          )}
        </div>
      )}
    </section>
  );
}
