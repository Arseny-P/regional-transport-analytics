import type { RailNodeKind } from '../model/types';

export const GRAPH_LINE_STYLES = {
  road: { color: '#555', weight: 2 },
  rail: { color: '#0F766E', weight: 3, dashArray: '6 4' },
};

export const RAIL_NODE_LABELS: Record<RailNodeKind, string> = {
  switch: 'Стрелочный перевод',
  junction: 'Узел соединения путей',
  endpoint: 'Конец пути',
  boundary: 'Вершина на границе области',
};

export function railNodeLabel(kind?: RailNodeKind) {
  return (kind && RAIL_NODE_LABELS[kind]) || 'Железнодорожная вершина';
}
