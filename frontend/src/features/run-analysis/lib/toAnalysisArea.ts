import type { BBox } from '@/entities/area';
import type { AnalysisArea } from '../api/createAnalysis';

export function toAnalysisArea({ minLat, minLng, maxLat, maxLng }: BBox): AnalysisArea {
  return {
    first_point: { latitude: minLat, longitude: minLng },
    second_point: { latitude: maxLat, longitude: maxLng },
  };
}
