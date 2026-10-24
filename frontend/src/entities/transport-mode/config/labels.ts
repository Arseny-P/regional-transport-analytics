import type { TransportMode } from '../model/types';

export const TRANSPORT_MODE_LABELS: Record<TransportMode, string> = {
  auto: 'Автомобильный',
  aero: 'Авиационный',
  sea: 'Морской',
  rail: 'Железнодорожный',
  all: 'Все режимы',
};
