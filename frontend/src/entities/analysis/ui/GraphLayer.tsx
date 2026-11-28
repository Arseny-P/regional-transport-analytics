import { useEffect, useMemo } from 'react';
import { latLngBounds, type LatLngTuple } from 'leaflet';
import { CircleMarker, Polyline, Tooltip, useMap } from 'react-leaflet';
import type { Position } from '@/shared/api';
import { METRIC_LABELS, formatMetricValue } from '../config/metricLabels';
import { GRAPH_LINE_STYLES } from '../config/graphStyles';
import { getEdgeTransport, getNodeTransport } from '../lib/graphTransport';
import { nodeColor, nodeMetricScale } from '../lib/nodeColor';
import type { Graph, GraphTransportMode, Metric, NodeSelection } from '../model/types';
import { RailNodeMarker } from './RailNodeMarker';

const WAREHOUSE_COLOR = '#6D4BD1';
const INTERSECTION_COLOR = '#475569';

const toLatLng = ([lng, lat]: Position): LatLngTuple => [lat, lng];

interface GraphLayerProps {
  graph: Graph;
  visibleModes: readonly GraphTransportMode[];
  metrics: Metric[];
  colorBy?: string;
  selection: NodeSelection | null;
  onNodeSelect: (selection: NodeSelection) => void;
}

export function GraphLayer({
  graph,
  visibleModes,
  metrics,
  colorBy,
  selection,
  onNodeSelect,
}: GraphLayerProps) {
  const map = useMap();

  const { bounds, lines, markers } = useMemo(() => {
    const bounds = latLngBounds([]);
    const segmentIds = new Set<string>();
    const lines: { id: string; mode: GraphTransportMode; positions: LatLngTuple[] }[] = [];

    for (const edge of graph.edges) {
      const { id, segment_id, geometry, attributes } = edge;
      const mode = getEdgeTransport(edge);
      if (!geometry || geometry.length < 2 || attributes?.edge_type === 'access_connector')
        continue;
      if (mode !== 'rail' && attributes?.edge_type !== 'road') continue;
      const segmentKey = segment_id ? `${mode}:${segment_id}` : undefined;
      if (segmentKey && segmentIds.has(segmentKey)) continue;

      const positions = geometry.map(toLatLng);
      lines.push({ id, mode, positions });
      for (const position of positions) bounds.extend(position);
      if (segmentKey) segmentIds.add(segmentKey);
    }

    const markers = graph.nodes
      .filter((node) => node.attributes?.object_type !== 'road_node')
      .map((node) => {
        const position = toLatLng(node.position);
        bounds.extend(position);
        return { node, position, mode: getNodeTransport(node) };
      });

    return { bounds, lines, markers };
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

  const visibleMarkers = markers.filter(({ mode }) => visibleModes.includes(mode));
  const { values, min, max } = nodeMetricScale(
    visibleMarkers.map(({ node }) => node),
    metrics,
    colorBy
  );

  return (
    <>
      {lines
        .filter(({ mode }) => visibleModes.includes(mode))
        .map(({ id, mode, positions }) => (
          <Polyline
            key={`${mode}:${id}`}
            positions={positions}
            pathOptions={GRAPH_LINE_STYLES[mode]}
          />
        ))}

      {visibleMarkers.map(({ node, position, mode }) => {
        const { id } = node;
        const type = node.attributes?.object_type;
        const warehouse = type === 'warehouse';
        const selectable = warehouse || type === 'intersection' || type === 'rail_node';
        const selected = selection?.id === id && selection.type === type;
        const radius = warehouse ? 9 : 6;
        const value = values.get(node.id);
        const defaultColor =
          mode === 'rail'
            ? GRAPH_LINE_STYLES.rail.color
            : warehouse
              ? WAREHOUSE_COLOR
              : INTERSECTION_COLOR;
        const color = value === undefined ? defaultColor : nodeColor(value, min, max);
        const events = selectable ? { click: () => onNodeSelect({ id, type }) } : undefined;
        const tooltip = value !== undefined && (
          <Tooltip>{`${METRIC_LABELS[colorBy ?? ''] ?? colorBy}: ${formatMetricValue(colorBy ?? '', value)}`}</Tooltip>
        );
        if (mode === 'rail') {
          return (
            <RailNodeMarker
              key={node.id}
              position={position}
              kind={node.attributes?.node_kind}
              color={color}
              selected={selected}
              eventHandlers={events}
            >
              {tooltip}
            </RailNodeMarker>
          );
        }
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
            eventHandlers={events}
          >
            {tooltip}
          </CircleMarker>
        );
      })}
    </>
  );
}
