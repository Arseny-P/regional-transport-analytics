// Подписи итоговых метрик из вики и поддерживаемых прежних показателей.
export const METRIC_LABELS: Readonly<Record<string, string>> = {
  warehouse_count: 'Количество складов',
  intersection_count: 'Количество перекрёстков',
  road_segment_count: 'Количество дорожных участков',
  isolated_warehouse_count: 'Складов без подключения к графу маршрутов',
  nearest_warehouse_distance_m: 'До ближайшего склада по дорогам',
  nearby_warehouse_count: 'Складов в заданном радиусе по дорогам',
  pagerank: 'PageRank',
  betweenness_centrality: 'Центральность по посредничеству',
  route_fraction: 'Доля складских маршрутов',
  vertex_count: 'Число вершин',
  edge_count: 'Число рёбер',
  avg_degree: 'Средняя степень вершины',
};

export const REGION_METRIC_NAMES = [
  'warehouse_count',
  'intersection_count',
  'road_segment_count',
  'isolated_warehouse_count',
] as const;

export const NODE_METRIC_NAMES = [
  'nearest_warehouse_distance_m',
  'nearby_warehouse_count',
  'pagerank',
  'betweenness_centrality',
  'route_fraction',
] as const;

// Значения API остаются в метрах и долях; преобразование применяется при отображении.
const METRIC_FORMATS: Readonly<
  Record<string, { scale: number; unit: string; maximumFractionDigits: number }>
> = {
  nearest_warehouse_distance_m: { scale: 0.001, unit: 'км', maximumFractionDigits: 3 },
  route_fraction: { scale: 100, unit: '%', maximumFractionDigits: 2 },
};

export function formatMetricValue(name: string, value: number | null | undefined, unit?: string) {
  if (value == null || !Number.isFinite(value)) return 'Не подключено';

  const format = unit === undefined ? METRIC_FORMATS[name] : undefined;
  const number = (value * (format?.scale ?? 1)).toLocaleString('ru-RU', {
    maximumFractionDigits: format?.maximumFractionDigits ?? 6,
  });
  const suffix = unit ?? format?.unit;
  return suffix ? `${number} ${suffix}` : number;
}

// Краткие пояснения выбранной метрики для легенды карты.
export const METRIC_DESCRIPTIONS: Readonly<Record<string, string>> = {
  nearest_warehouse_distance_m:
    'Кратчайшее расстояние по дорогам от выбранного склада до другого склада с учётом направления движения. Служебные связи с дорогой в расстояние не входят.',
  nearby_warehouse_count:
    'Число других складов, до которых можно доехать по направленному дорожному маршруту в пределах заданного радиуса. Порог одинаков для всех складов анализа.',
  pagerank: 'Структурная значимость перекрёстка с учётом связей и направлений дорожной сети.',
  betweenness_centrality:
    'Показывает, как часто перекрёсток встречается на кратчайших по длине путях между дорожными вершинами.',
  route_fraction:
    'Доля найденных направленных маршрутов между складами, проходящих через этот перекрёсток. Отображается в процентах.',
};
