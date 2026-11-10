import { useEffect, useMemo } from 'react';
import type { LatLngTuple } from 'leaflet';
import { CircleMarker, Polyline, Tooltip, useMap } from 'react-leaflet';
import type { Position } from '@/shared/api';
import { nodeColor } from '../lib/nodeColor';
import type { Graph } from '../model/types';

const DEFAULT_NODE_COLOR = '#0f62fe';

const toLatLng = ([lng, lat]: Position): LatLngTuple => [lat, lng];

interface GraphLayerProps {
  graph: Graph;
  colorBy?: string;
}

export function GraphLayer({ graph, colorBy }: GraphLayerProps) {
  const map = useMap();

  const nodePositions = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, toLatLng(node.position)])),
    [graph]
  );

  useEffect(() => {
    if (nodePositions.size) map.fitBounds([...nodePositions.values()], { padding: [40, 40] });
  }, [map, nodePositions]);

  const values = graph.nodes.map((node) => node.attributes?.[colorBy ?? '']);
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
              pathOptions={{ color: '#555', weight: 2 }}
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
            radius={6}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.9 }}
          >
            {typeof value === 'number' && <Tooltip>{`${colorBy}: ${value}`}</Tooltip>}
          </CircleMarker>
        );
      })}
    </>
  );
}
