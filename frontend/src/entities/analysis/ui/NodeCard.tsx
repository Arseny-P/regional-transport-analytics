import { Button } from '@/shared/ui';
import styles from './NodeCard.module.css';

type NodeKind = 'warehouse' | 'intersection';

interface NodeMetric {
  id: string;
  label: string;
  value?: number | null;
  unit?: string;
}

interface NodeCardProps {
  node: {
    id: string;
    kind: NodeKind;
    name?: string;
    connectionStatus?: string;
  };
  metrics: NodeMetric[];
  onClose: () => void;
}

const KIND_LABELS: Record<NodeKind, string> = {
  warehouse: 'Склад',
  intersection: 'Перекрёсток',
};

export function NodeCard({ node, metrics, onClose }: NodeCardProps) {
  const kindLabel = KIND_LABELS[node.kind];
  const title = node.name?.trim() || kindLabel;

  return (
    <section className={styles.card} aria-label={`Карточка: ${title}`}>
      <div className={styles.header}>
        <h3>{title}</h3>
        <Button onClick={onClose}>Закрыть</Button>
      </div>

      <p className={styles.details}>
        {kindLabel} · ID: {node.id}
      </p>

      {node.kind === 'warehouse' && node.connectionStatus && (
        <p className={styles.details}>
          Подключение: {node.connectionStatus}
        </p>
      )}

      {metrics.length > 0 ? (
        <table className={styles.metricsTable} aria-label="Показатели вершины">
          <thead>
            <tr>
              <th scope="col">Показатель</th>
              <th scope="col">Значение</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map(({ id, label, value, unit }) => (
              <tr key={id}>
                <th scope="row">{label}</th>
                <td>
                  {value == null
                    ? 'Не рассчитано'
                    : `${value.toLocaleString('ru-RU')}${unit ? ` ${unit}` : ''}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className={styles.details}>Для этой вершины нет показателей.</p>
      )}
    </section>
  );
}