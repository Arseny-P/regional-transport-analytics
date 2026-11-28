import type { GraphNode, Metric } from '../model/types';
import { METRIC_LABELS } from './metricLabels';

const warehouseMetrics = ['nearest_warehouse_distance_m', 'nearby_warehouse_count'];
const intersectionMetrics = ['pagerank', 'betweenness_centrality', 'route_fraction'];

export function getNodeMetricRows(node: GraphNode, metrics: readonly Metric[]) {
  const values = new Map(
    metrics.filter((metric) => metric.node_id === node.id).map(({ name, value }) => [name, value])
  );
  const kind = node.attributes?.object_type;
  if (kind === 'rail_node') {
    const degree = node.attributes?.physical_degree;
    const centrality = values.get('betweenness_centrality');
    return [
      ...(degree === undefined
        ? []
        : [{ id: 'physical_degree', label: 'Степень вершины', value: degree }]),
      ...(centrality === undefined
        ? []
        : [
            {
              id: 'betweenness_centrality',
              label: METRIC_LABELS.betweenness_centrality,
              value: centrality,
            },
          ]),
    ];
  }
  const names =
    kind === 'warehouse' ? warehouseMetrics : kind === 'intersection' ? intersectionMetrics : [];

  return names.map((id) => ({
    id,
    label: METRIC_LABELS[id] ?? id,
    value: values.get(id) ?? null,
  }));
}
