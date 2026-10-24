export const TRANSPORT_MODES = ['auto', 'aero', 'sea', 'rail', 'all'] as const;

export type TransportMode = (typeof TRANSPORT_MODES)[number];

export type SingleTransportMode = Exclude<TransportMode, 'all'>;

export const DEFAULT_TRANSPORT_MODE: TransportMode = 'auto';
