import type { OpenApiGraph, RoadGraphData, RoadGraphFeature } from '../model/types';

export function mapOpenApiGraphToGeoJSON(graph: OpenApiGraph): RoadGraphData {
  const nodesMap = new Map(graph.nodes.map((n) => [n.id, n]));

  const nodeFeatures: RoadGraphFeature[] = graph.nodes.map((node) => ({
    type: 'Feature',
    geometry: {
      type: 'Point',
      coordinates: [node.lon, node.lat], // СТРОГО [долгота, широта]
    },
    properties: {
      kind: 'node',
      id: node.id,
      name: node.name ?? `Узел ${node.id}`,
      type: node.type ?? 'unknown',
      ...node.properties,
    },
  }));

  const edgeFeatures: RoadGraphFeature[] = [];

  for (const edge of graph.edges) {
    const fromNode = nodesMap.get(edge.from);
    const toNode = nodesMap.get(edge.to);

    if (!fromNode || !toNode) {
      console.warn(`[mapOpenApiGraph] Edge ссылается на несуществующие ноды: from=${edge.from}, to=${edge.to}`);
      continue;
    }

    // Используем геометрию маршрута, если она есть, иначе прямая линия
    const coordinates: [number, number][] =
      edge.geometry && edge.geometry.length >= 2
        ? edge.geometry
        : [[fromNode.lon, fromNode.lat], [toNode.lon, toNode.lat]];

    edgeFeatures.push({
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates,
      },
      properties: {
        kind: 'edge',
        id: edge.id,
        from: edge.from,
        to: edge.to,
        type: edge.type ?? 'road',
        distance: edge.distance,
        ...edge.properties,
      },
    });
  }

  return {
    type: 'FeatureCollection',
    features: [...nodeFeatures, ...edgeFeatures],
  };
}

export function createEmptyGraph(): RoadGraphData {
  return { type: 'FeatureCollection', features: [] };
}