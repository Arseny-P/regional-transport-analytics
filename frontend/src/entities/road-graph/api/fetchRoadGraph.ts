import type { RoadGraphData, LogisticsPoint, OpenApiGraph } from '../model/types';
import { mapOpenApiGraphToGeoJSON } from './mapOpenApiGraph';

function isOpenApiGraph(data: unknown): data is OpenApiGraph {
  if (typeof data !== 'object' || data === null) return false;
  const d = data as Record<string, unknown>;
  return Array.isArray(d.nodes) && Array.isArray(d.edges) && d.type !== 'FeatureCollection';
}

export const fetchRoadGraph = async (url: string): Promise<RoadGraphData | null> => {
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    const raw = await response.json();

    if (isOpenApiGraph(raw)) {
      console.info('[fetchRoadGraph] Обнаружен OpenAPI Graph, применяем адаптер');
      return mapOpenApiGraphToGeoJSON(raw);
    }
    return raw as RoadGraphData;
  } catch (err) {
    console.error(`Ошибка загрузки графа по адресу ${url}:`, err);
    return null;
  }
};

export const fetchOriginalPoints = async (url: string): Promise<LogisticsPoint[]> => {
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    return await response.json();
  } catch (err) {
    console.error(`Ошибка загрузки точек по адресу ${url}:`, err);
    return [];
  }
};