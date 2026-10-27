export const TRANSPORT_MODES = ['road', 'rail', 'sea'] as const;

export type TransportMode = (typeof TRANSPORT_MODES)[number];

export const DEFAULT_TRANSPORT_MODES: TransportMode[] = ['road'];
