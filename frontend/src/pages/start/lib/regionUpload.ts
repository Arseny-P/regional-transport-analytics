import { ApiError } from '@/shared/api';

const MAX_REGION_FILE_SIZE = 20_000_000;
const SIZE_ERROR = 'Файл GeoJSON не должен превышать 20 МБ.';
const FORMAT_ERROR = 'Выберите GeoJSON с границами Polygon или MultiPolygon в FeatureCollection.';

function isPolygonFeature(feature: unknown): boolean {
  if (
    typeof feature !== 'object' ||
    feature === null ||
    !('type' in feature) ||
    feature.type !== 'Feature' ||
    !('geometry' in feature)
  ) {
    return false;
  }

  const { geometry } = feature;
  return (
    typeof geometry === 'object' &&
    geometry !== null &&
    'type' in geometry &&
    (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon')
  );
}

export async function validateRegionFile(file: File): Promise<string | null> {
  if (file.size > MAX_REGION_FILE_SIZE) return SIZE_ERROR;

  let contents: unknown;
  try {
    contents = JSON.parse(await file.text());
  } catch {
    return 'Не удалось прочитать файл. Проверьте, что он содержит корректный GeoJSON.';
  }

  if (
    typeof contents !== 'object' ||
    contents === null ||
    !('type' in contents) ||
    contents.type !== 'FeatureCollection' ||
    !('features' in contents) ||
    !Array.isArray(contents.features) ||
    !contents.features.length ||
    !contents.features.every(isPolygonFeature)
  ) {
    return FORMAT_ERROR;
  }

  return null;
}

export function getRegionUploadError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return 'Не удалось связаться с сервером. Проверьте соединение и повторите загрузку.';
  }
  if (error.status === 413) return SIZE_ERROR;
  if (error.code === 'invalid_json') return 'Файл содержит некорректный JSON.';
  if (error.code === 'invalid_region_file') {
    return 'Граница региона некорректна. Проверьте координаты и замкнутость контуров.';
  }
  return 'Сервер не смог загрузить регион. Попробуйте ещё раз.';
}
