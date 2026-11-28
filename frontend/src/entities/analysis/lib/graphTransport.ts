import { GRAPH_TRANSPORT_MODES, type Graph, type GraphEdge, type GraphNode } from '../model/types';

export function getNodeTransport(node: GraphNode) {
  return (
    node.attributes?.transport_mode ??
    (node.attributes?.object_type === 'rail_node' ? 'rail' : 'road')
  );
}

export function getEdgeTransport(edge: GraphEdge) {
  return edge.attributes?.transport_mode ?? 'road';
}

export function getGraphTransports(graph: Graph) {
  return GRAPH_TRANSPORT_MODES.filter(
    (mode) =>
      graph.nodes.some((node) => getNodeTransport(node) === mode) ||
      graph.edges.some((edge) => getEdgeTransport(edge) === mode)
  );
}
