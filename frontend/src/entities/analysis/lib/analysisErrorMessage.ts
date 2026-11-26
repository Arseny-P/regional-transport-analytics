import { ApiError } from '@/shared/api';

const MESSAGES: Readonly<Record<string, string>> = {
  invalid_parameters:
    'Проверьте координаты области и выбранные виды транспорта, затем запустите анализ снова.',
  invalid_coordinates:
    'Проверьте координаты: широта должна быть от −90 до 90, долгота — от −180 до 180.',
  invalid_area: 'Выберите две разные точки, образующие область ненулевой площади.',
  area_outside_region:
    'Выбранная область выходит за границы региона. Выделите участок внутри выбранного региона.',
  invalid_transports: 'Выберите хотя бы один доступный вид транспорта.',
  unsupported_transport:
    'Выбранный вид транспорта пока недоступен для анализа. Измените параметры.',
  invalid_region_id: 'Не удалось определить выбранный регион. Выберите регион заново.',
  region_not_found: 'Выбранный регион больше недоступен. Вернитесь к выбору региона.',
  storage_error:
    'Не удалось загрузить данные региона. Попробуйте позже или выберите другой регион.',
  missing_job_id: 'Не удалось определить анализ. Запустите новый анализ с выбранными параметрами.',
  invalid_job_id:
    'Ссылка на анализ некорректна. Откройте правильную ссылку или запустите новый анализ.',
  job_not_found: 'Анализ не найден. Проверьте ссылку или запустите новый анализ.',
  job_parameters_conflict: 'Не удалось запустить анализ с этими параметрами. Повторите запуск.',
  job_already_finished: 'Анализ уже завершился, отмена больше недоступна. Получаем его результат.',
  heartbeat_timeout_exceeded:
    'Анализ остановлен: связь со страницей была потеряна. Запустите анализ снова.',
  analysis_canceled: 'Анализ отменён. Можно выбрать другие параметры и запустить его снова.',
  osm_unavailable: 'Сервис дорожных данных сейчас недоступен. Попробуйте запустить анализ позже.',
  graph_build_failed:
    'Не удалось построить дорожную сеть. Выберите другую область и запустите анализ снова.',
  metrics_calculation_failed:
    'Не удалось рассчитать показатели графа. Доступный граф можно просмотреть или запустить анализ заново.',
  invalid_json: 'Не удалось отправить параметры анализа. Обновите страницу и попробуйте снова.',
  file_too_large: 'Файл слишком большой. Выберите файл размером до 20 МБ.',
  missing_file: 'Выберите файл с границей региона.',
  invalid_multipart: 'Не удалось загрузить файл. Выберите один файл и повторите загрузку.',
  unsupported_media_type: 'Не удалось отправить файл в поддерживаемом формате. Повторите загрузку.',
  invalid_region_file:
    'Файл должен содержать границу региона в GeoJSON с геометрией Polygon или MultiPolygon.',
  internal_db_error: 'Сервис временно не может получить данные анализа. Попробуйте позже.',
  internal_error:
    'Не удалось завершить анализ из-за ошибки сервиса. Попробуйте запустить его снова позже.',
};

export function analysisErrorMessage(error: { code?: string; message: string }): string {
  if (/MessageSizeTooLargeError|max_request_size/i.test(error.message)) {
    return 'Для выбранной области получилось слишком много данных. Выберите область поменьше и запустите анализ снова.';
  }
  const code = error.code ?? '';
  return Object.hasOwn(MESSAGES, code)
    ? MESSAGES[code]
    : 'Не удалось выполнить операцию. Попробуйте ещё раз позже.';
}

export function analysisRequestErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return 'Не удалось связаться с сервером. Проверьте подключение к интернету и повторите попытку.';
  }
  if (error.code && Object.hasOwn(MESSAGES, error.code)) return analysisErrorMessage(error);
  if (error.status === 429) return 'Слишком много запросов. Подождите немного и попробуйте снова.';
  if (error.status >= 500) return 'Сервис временно недоступен. Попробуйте ещё раз позже.';
  if (error.status === 401 || error.status === 403)
    return 'Нет доступа к этим данным. Обновите страницу или обратитесь к команде сервиса.';
  return analysisErrorMessage(error);
}

export function isRetryableAnalysisRequest(error: unknown): boolean {
  return (
    !(error instanceof ApiError) ||
    error.status >= 500 ||
    error.status === 408 ||
    error.status === 429
  );
}
