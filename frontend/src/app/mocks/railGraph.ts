import type { Graph, RailNodeKind } from '@/entities/analysis';
import type { Position } from '@/shared/api';

const NODES: [longitudeFraction: number, latitudeFraction: number, kind: RailNodeKind][] = [
  [0, 0.53, 'boundary'],
  [0.23, 0.53, 'switch'],
  [0.5, 0.58, 'junction'],
  [0.75, 0.48, 'switch'],
  [1, 0.48, 'boundary'],
  [0.3, 0.76, 'endpoint'],
  [0.46, 0.22, 'endpoint'],
  [0.85, 0.73, 'endpoint'],
];

const SEGMENTS: [source: number, target: number][] = [
  [0, 1],
  [1, 2],
  [2, 3],
  [3, 4],
  [1, 5],
  [2, 6],
  [3, 7],
];

export function buildRailGraph(first: Position, second: Position): Graph {
  const nodes: Graph['nodes'] = NODES.map(([longitude, latitude, kind], index) => ({
    id: `rail-node-${index}`,
    position: [
      first[0] + longitude * (second[0] - first[0]),
      first[1] + latitude * (second[1] - first[1]),
    ],
    attributes: {
      transport_mode: 'rail',
      object_type: 'rail_node',
      node_kind: kind,
      physical_degree: SEGMENTS.filter(([source, target]) => source === index || target === index)
        .length,
    },
  }));

  const edges: Graph['edges'] = SEGMENTS.flatMap(([source, target], index) => {
    const segmentId = `rail-segment-${index}`;
    return [
      [source, target],
      [target, source],
    ].map(([from, to]) => ({
      id: `${segmentId}:${from}-${to}`,
      segment_id: segmentId,
      source: nodes[from].id,
      target: nodes[to].id,
      geometry: [nodes[from].position, nodes[to].position],
      attributes: { transport_mode: 'rail' },
    }));
  });

  return { nodes, edges };
}
