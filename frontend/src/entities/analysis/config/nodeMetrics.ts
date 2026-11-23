import type { GraphNode, Metric } from '../model/types';

// Предварительные подписи и ключи по #71; сверить с итоговым контрактом воркера.
const warehouseMetrics = [
  { id: 'reachable_warehouses_count', label: 'Достижимые склады' },
  { id: 'avg_distance_to_warehouses_km', label: 'Среднее расстояние до складов', unit: 'км' },
  { id: 'weighted_closeness', label: 'Взвешенная близость' },
];

const intersectionMetrics = [
  { id: 'pagerank', label: 'Важность (PageRank)' },
  { id: 'betweenness_centrality', label: 'Центральность по посредничеству' },
  { id: 'warehouse_route_share', label: 'Доля маршрутов между складами' },
];

export function getNodeMetricRows(node: GraphNode, metrics: readonly Metric[]) {
  const values = new Map(
    metrics.filter((metric) => metric.node_id === node.id).map(({ name, value }) => [name, value])
  );
  const kind = node.attributes?.object_type;
  const definitions =
    kind === 'warehouse'
      ? warehouseMetrics
      : kind === 'intersection'
        ? intersectionMetrics
        : [];

  return [{ id: 'degree', label: 'Степень вершины' }, ...definitions].map((definition) => ({
    ...definition,
    value: values.get(definition.id) ?? null,
  }));
}
