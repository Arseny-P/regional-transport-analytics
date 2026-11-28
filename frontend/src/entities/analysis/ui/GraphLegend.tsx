import { METRIC_LABELS, METRIC_DESCRIPTIONS, formatMetricValue } from '../config/metricLabels';
import { GRAPH_LINE_STYLES, RAIL_NODE_LABELS } from '../config/graphStyles';
import { nodeMetricScale } from '../lib/nodeColor';
import type { GraphNode, GraphTransportMode, Metric } from '../model/types';
import styles from './GraphLegend.module.css';
import markerStyles from './RailNodeMarker.module.css';

interface GraphLegendProps {
  colorBy?: string;
  nodes: readonly GraphNode[];
  visibleModes: readonly GraphTransportMode[];
  metrics?: readonly Metric[];
}

export function GraphLegend({ colorBy, nodes, visibleModes, metrics = [] }: GraphLegendProps) {
  const { min, max } = nodeMetricScale(nodes, metrics, colorBy);
  const hasValues = Number.isFinite(min) && Number.isFinite(max);
  return (
    <section className={styles.legend} aria-label="Легенда графа">
      <h4 className={styles.title}>Легенда</h4>
      <ul className={styles.items}>
        {visibleModes.includes('road') && (
          <>
            <li className={styles.row}>
              <span className={styles.warehouse} aria-hidden="true" />
              <span>Склады</span>
            </li>
            <li className={styles.row}>
              <span className={styles.intersection} aria-hidden="true" />
              <span>Перекрёстки</span>
            </li>
            <li className={styles.row}>
              <span
                className={styles.road}
                style={{ backgroundColor: GRAPH_LINE_STYLES.road.color }}
                aria-hidden="true"
              />
              <span>Автомобильные участки маршрутов</span>
            </li>
          </>
        )}
        {visibleModes.includes('rail') && (
          <>
            <li className={styles.row}>
              <span
                className={styles.rail}
                style={{ borderColor: GRAPH_LINE_STYLES.rail.color }}
                aria-hidden="true"
              />
              <span>Железнодорожные пути</span>
            </li>
            {Object.entries(RAIL_NODE_LABELS).map(([kind, label]) => (
              <li key={kind} className={styles.row}>
                <span
                  className={styles.railNode}
                  style={{ color: GRAPH_LINE_STYLES.rail.color }}
                  aria-hidden="true"
                >
                  <span className={markerStyles.symbol} data-kind={kind} />
                </span>
                <span>{label}</span>
              </li>
            ))}
          </>
        )}
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
