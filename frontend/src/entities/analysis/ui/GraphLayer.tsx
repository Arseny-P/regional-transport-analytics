import { useEffect, useMemo } from 'react';
import { latLngBounds, type LatLngTuple } from 'leaflet';
import { CircleMarker, Polyline, Tooltip, useMap } from 'react-leaflet';
import type { Position } from '@/shared/api';
import { nodeColor } from '../lib/nodeColor';
import type { Graph, Metric, NodeSelection } from '../model/types';

const WAREHOUSE_COLOR = '#0f62fe';
const INTERSECTION_COLOR = '#475569';

const toLatLng = ([lng, lat]: Position): LatLngTuple => [lat, lng];

interface GraphLayerProps {
  graph: Graph;
  metrics: Metric[];
  colorBy?: string;
  selection: NodeSelection | null;
  onNodeSelect: (selection: NodeSelection) => void;
}

export function GraphLayer({ graph, metrics, colorBy, selection, onNodeSelect }: GraphLayerProps) {
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
        const position = toLatLng(node.position);
        bounds.extend(position);
        return { node, position };
      });

    return { bounds, roads, markers };
  }, [graph]);

  const southWest = bounds.getSouthWest();
  const northEast = bounds.getNorthEast();
  const south = southWest?.lat;
  const west = southWest?.lng;
  const north = northEast?.lat;
  const east = northEast?.lng;

  useEffect(() => {
    if (south === undefined || west === undefined || north === undefined || east === undefined) {
      return;
    }
    map.fitBounds(
      [
        [south, west],
        [north, east],
      ],
      { padding: [40, 40], maxZoom: 17 }
    );
  }, [map, south, west, north, east]);

  const values = new Map<string, number>();
  for (const { node_id, name, value } of metrics) {
    if (node_id !== undefined && name === colorBy && Number.isFinite(value)) {
      if (!values.has(node_id)) values.set(node_id, value);
    }
  }
  let min = Infinity;
  let max = -Infinity;
  for (const { node } of markers) {
    const value = values.get(node.id);
    if (value === undefined) continue;
    min = Math.min(min, value);
    max = Math.max(max, value);
  }

  return (
    <>
      {roads.map(({ id, positions }) => (
        <Polyline key={id} positions={positions} pathOptions={{ color: '#555', weight: 2 }} />
      ))}

      {markers.map(({ node, position }) => {
        const { id } = node;
        const type = node.attributes?.object_type;
        const warehouse = type === 'warehouse';
        const selectable = warehouse || type === 'intersection';
        const selected = selection?.id === id && selection.type === type;
        const radius = warehouse ? 9 : 6;
        const value = values.get(node.id);
        const defaultColor = warehouse ? WAREHOUSE_COLOR : INTERSECTION_COLOR;
        const color = value === undefined ? defaultColor : nodeColor(value, min, max);
        return (
          <CircleMarker
            key={node.id}
            center={position}
            radius={selected ? radius + 3 : radius}
            pathOptions={{
              color: selected ? '#111827' : color,
              weight: selected ? 4 : 3,
              fillColor: color,
              fillOpacity: 0.9,
            }}
            eventHandlers={selectable ? { click: () => onNodeSelect({ id, type }) } : undefined}
          >
            {value !== undefined && <Tooltip>{`${colorBy}: ${value}`}</Tooltip>}
          </CircleMarker>
        );
      })}
    </>
  );
}
