import type { CSSProperties } from 'react';
import { REGIONS_CONFIG } from '../config/regions';
import styles from './RoadGraphLegend.module.css';

interface RoadGraphLegendProps {
  className?: string;
}

export function RoadGraphLegend({ className }: RoadGraphLegendProps) {
  return (
    <div className={[styles.legend, className].filter(Boolean).join(' ')}>
      <div className={styles.title}>Легенда:</div>
      {REGIONS_CONFIG.map((region) => (
        <div
          key={region.id}
          className={styles.region}
          style={
            {
              '--region-color': region.color,
              '--point-color': region.pointColor,
            } as CSSProperties
          }
        >
          <div className={styles.regionTitle}>{region.label}:</div>

          {/* Логистические объекты (точки) */}
          <div className={styles.pointsRow}>
            <div className={styles.point} />
            <span>Логистические объекты</span>
          </div>

          {/* Транспортные связи (линии) */}
          <div className={styles.row}>
            <div className={styles.line} />
            <span>Транспортные связи</span>
          </div>
        </div>
      ))}
    </div>
  );
}
