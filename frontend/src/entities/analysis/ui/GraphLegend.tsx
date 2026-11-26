import styles from './GraphLegend.module.css';

interface GraphLegendProps {
  coloredByMetric?: boolean;
}

export function GraphLegend({ coloredByMetric = false }: GraphLegendProps) {
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
      {coloredByMetric && <p className={styles.note}>Цвет точек зависит от выбранной метрики.</p>}
    </section>
  );
}
