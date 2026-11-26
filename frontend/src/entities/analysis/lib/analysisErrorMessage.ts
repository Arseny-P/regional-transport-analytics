import type { AnalysisFailure } from '../model/types';

const MESSAGES: Readonly<Record<string, string>> = {
  invalid_parameters:
    'Не удалось начать анализ с выбранными параметрами. Проверьте область и виды транспорта.',
  unsupported_transport:
    'Выбранный вид транспорта пока недоступен для анализа. Измените параметры и попробуйте снова.',
  osm_unavailable: 'Не удалось получить данные дорожной сети. Попробуйте запустить анализ позже.',
  graph_build_failed:
    'Не удалось построить дорожную сеть для выбранной области. Выберите другую область и попробуйте снова.',
  metrics_calculation_failed:
    'Не удалось рассчитать показатели графа. Попробуйте запустить анализ снова.',
};

export function analysisErrorMessage(error: AnalysisFailure): string {
  if (/MessageSizeTooLargeError|max_request_size/i.test(error.message)) {
    return 'Для выбранной области получилось слишком много данных. Выберите область поменьше и запустите анализ снова.';
  }
  return (
    MESSAGES[error.code] ??
    'Не удалось завершить анализ из-за ошибки сервиса. Попробуйте запустить анализ снова позже.'
  );
}
