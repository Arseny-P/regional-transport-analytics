import { ApiError } from '@/shared/api';

const MESSAGES: Record<string, string> = {
  area_outside_region: 'Выделенная область выходит за границу региона.',
  job_parameters_conflict: 'Задача с таким идентификатором уже запущена с другими параметрами.',
};

export function errorMessage(error: Error): string {
  if (!(error instanceof ApiError)) return 'Не удалось связаться с сервером анализа.';
  if (error.code && MESSAGES[error.code]) return MESSAGES[error.code];
  if (error.status === 404) return 'Регион не найден.';
  return error.message;
}
