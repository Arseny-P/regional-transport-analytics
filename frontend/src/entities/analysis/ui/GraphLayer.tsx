import { useEffect, useMemo } from 'react';
import type { LatLngTuple } from 'leaflet';
import { CircleMarker, Polyline, Tooltip, useMap } from 'react-leaflet';
import type { Position } from '@/shared/api';
import { nodeColor } from '../lib/nodeColor';
import type { Graph, Metric } from '../model/types';

const DEFAULT_NODE_COLOR = '#0f62fe';

const toLatLng = ([lng, lat]: Position): LatLngTuple => [lat, lng];

interface GraphLayerProps {
  graph: Graph;
  metrics: Metric[];
  colorBy?: string;
  onNodeHover?: (nodeId: string) => void;
}

export function GraphLayer({ graph, metrics, colorBy, onNodeHover }: GraphLayerProps) {
  const map = useMap();

  const nodePositions = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, toLatLng(node.position)])),
    [graph]
  );

  useEffect(() => {
    if (nodePositions.size) map.fitBounds([...nodePositions.values()], { padding: [40, 40] });
  }, [map, nodePositions]);

  const values = graph.nodes.map(
    (node) => metrics.find((m) => m.node_id === node.id && m.name === colorBy)?.value
  );
  const numbers = values.filter((value): value is number => typeof value === 'number');
  const min = Math.min(...numbers);
  const max = Math.max(...numbers);

  return (
    <>
      {graph.edges.map((edge) => {
        const source = nodePositions.get(edge.source);
        const target = nodePositions.get(edge.target);
        const positions = edge.geometry?.map(toLatLng) ?? (source && target && [source, target]);
        return (
          positions && (
            <Polyline
              key={edge.id}
              positions={positions}
              pathOptions={{
                color: edge.attributes?.edge_type === 'access_connector' ? '#888' : '#555',
                weight: 2,
                dashArray: edge.attributes?.edge_type === 'access_connector' ? '4 4' : undefined,
              }}
            />
          )
        );
      })}

      {graph.nodes.map((node, index) => {
        const value = values[index];
        const color = typeof value === 'number' ? nodeColor(value, min, max) : DEFAULT_NODE_COLOR;
        return (
          <CircleMarker
            key={node.id}
            center={toLatLng(node.position)}
            radius={
              node.attributes?.object_type === 'warehouse'
                ? 9
                : node.attributes?.object_type === 'road_node'
                  ? 4
                  : 6
            }
            pathOptions={{ color, fillColor: color, fillOpacity: 0.9 }}
            eventHandlers={{ mouseover: () => onNodeHover?.(node.id) }}
          >
            {typeof value === 'number' && <Tooltip>{`${colorBy}: ${value}`}</Tooltip>}
          </CircleMarker>
        );
      })}
    </>
  );
}
