import type { GraphNode, Metric } from '../model/types';

export function nodeColor(value: number, min: number, max: number): string {
  const ratio = max > min ? (value - min) / (max - min) : 1;
  return `hsl(${Math.round(220 * (1 - ratio))}, 80%, 45%)`;
}

// Общий набор значений и диапазон для отрисовки точек и легенды.
export function nodeMetricScale(
  nodes: readonly GraphNode[],
  metrics: readonly Metric[],
  name?: string
) {
  const visibleIds = new Set(
    nodes.filter((node) => node.attributes?.object_type !== 'road_node').map((node) => node.id)
  );
  const values = new Map<string, number>();
  let min = Infinity;
  let max = -Infinity;
  for (const metric of metrics) {
    const { node_id, value } = metric;
    if (
      node_id === undefined ||
      metric.name !== name ||
      !visibleIds.has(node_id) ||
      !Number.isFinite(value) ||
      values.has(node_id)
    )
      continue;
    values.set(node_id, value);
    min = Math.min(min, value);
    max = Math.max(max, value);
  }
  return { values, min, max };
}
