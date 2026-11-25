import { useEffect, useMemo } from 'react';
import { latLngBounds, type LatLngTuple } from 'leaflet';
import { CircleMarker, Polyline, Tooltip, useMap } from 'react-leaflet';
import type { Position } from '@/shared/api';
import { METRIC_LABELS } from '../config/metricLabels';
import { nodeColor } from '../lib/nodeColor';
import type { Graph, Metric } from '../model/types';
import styles from './GraphLayer.module.css';

const ROAD_STYLE = { color: '#555', weight: 2 };
const NODE_STYLES = {
  warehouse: { label: 'Склады', color: '#0f62fe', radius: 9 },
  intersection: { label: 'Перекрёстки', color: '#475569', radius: 6 },
  other: { label: 'Другие узлы', color: '#475569', radius: 6 },
};
const metricNumber = new Intl.NumberFormat('ru-RU', { maximumSignificantDigits: 8 });

const toLatLng = ([lng, lat]: Position): LatLngTuple => [lat, lng];

interface NodeStyle {
  label: string;
  color: string;
  radius: number;
}

interface GraphLayerProps {
  graph: Graph;
  metrics: Metric[];
  colorBy?: string;
  onNodeHover?: (nodeId: string) => void;
}

export function GraphLayer({ graph, metrics, colorBy, onNodeHover }: GraphLayerProps) {
  const map = useMap();

  const { bounds, roads, markers } = useMemo(() => {
    const bounds = latLngBounds([]);
    const segmentIds = new Set<string>();
    const roads: { id: string; positions: LatLngTuple[] }[] = [];

    for (const { id, segment_id, geometry, attributes } of graph.edges) {
      if (attributes?.edge_type !== 'road' || !geometry || geometry.length < 2) continue;
      if (segment_id && segmentIds.has(segment_id)) continue;

      const positions = geometry.map(toLatLng);
      roads.push({ id, positions });
      for (const position of positions) bounds.extend(position);
      if (segment_id) segmentIds.add(segment_id);
    }

    const markers = graph.nodes
      .filter((node) => node.attributes?.object_type !== 'road_node')
      .map((node) => {
        const type = node.attributes?.object_type;
        const style = NODE_STYLES[type === 'warehouse' || type === 'intersection' ? type : 'other'];
        const position = toLatLng(node.position);
        bounds.extend(position);
        return { node, position, style };
      });

    return { bounds, roads, markers };
  }, [graph]);

  useEffect(() => {
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
  }, [map, bounds]);

  const values = new Map<string, number>();
  for (const { node_id, name, value } of metrics) {
    if (node_id !== undefined && name === colorBy && Number.isFinite(value)) {
      if (!values.has(node_id)) values.set(node_id, value);
    }
  }
  let min = Infinity;
  let max = -Infinity;
  const legendNodes = new Map<NodeStyle, boolean>();
  for (const { node, style } of markers) {
    const value = values.get(node.id);
    legendNodes.set(style, legendNodes.get(style) === true || value === undefined);
    if (value === undefined) continue;
    min = Math.min(min, value);
    max = Math.max(max, value);
  }

  const hasMetric = !!colorBy && Number.isFinite(min);
  const metricColors = hasMetric
    ? [0, 0.25, 0.5, 0.75, 1].map((fraction) => nodeColor(min + (max - min) * fraction, min, max))
    : [];

  return (
    <>
      {roads.map(({ id, positions }) => (
        <Polyline key={id} positions={positions} pathOptions={ROAD_STYLE} />
      ))}

      {markers.map(({ node, position, style }) => {
        const value = values.get(node.id);
        const color = value === undefined ? style.color : nodeColor(value, min, max);
        return (
          <CircleMarker
            key={node.id}
            center={position}
            radius={style.radius}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.9 }}
            eventHandlers={{ mouseover: () => onNodeHover?.(node.id) }}
          >
            {value !== undefined && <Tooltip>{`${colorBy}: ${value}`}</Tooltip>}
          </CircleMarker>
        );
      })}

      {(roads.length > 0 || legendNodes.size > 0) && (
        <aside aria-label="Легенда графа" className={styles.legend}>
          <strong>Легенда</strong>
          <ul className={styles.items}>
            {roads.length > 0 && (
              <li>
                <span className={styles.line} style={{ backgroundColor: ROAD_STYLE.color }} />
                Дороги
              </li>
            )}
            {Object.values(NODE_STYLES).map(
              (style) =>
                legendNodes.has(style) && (
                  <li key={style.label}>
                    <span className={styles.symbol}>
                      <span
                        className={styles.dot}
                        style={{
                          width: style.radius * 2,
                          height: style.radius * 2,
                          backgroundColor: legendNodes.get(style) ? style.color : undefined,
                        }}
                      />
                    </span>
                    {style.label}
                  </li>
                )
            )}
          </ul>
          {hasMetric && (
            <div className={styles.metric}>
              <div>{METRIC_LABELS[colorBy] ?? colorBy}</div>
              <div
                className={styles.scale}
                style={{
                  background: `linear-gradient(to right, ${metricColors.join(', ')})`,
                }}
              />
              <div className={styles.scaleLabels}>
                <span>{metricNumber.format(min)}</span>
                {min !== max && <span>{metricNumber.format(max)}</span>}
              </div>
            </div>
          )}
        </aside>
      )}
    </>
  );
}
