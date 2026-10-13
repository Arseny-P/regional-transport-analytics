import type { LatLngLiteral } from 'leaflet';
import type { BBox } from '../model/types';

export function bboxFromPoints(p1: LatLngLiteral, p2: LatLngLiteral): BBox {
  return {
    minLat: Math.min(p1.lat, p2.lat),
    maxLat: Math.max(p1.lat, p2.lat),
    minLng: Math.min(p1.lng, p2.lng),
    maxLng: Math.max(p1.lng, p2.lng),
  };
}

export function parseLatLng(value: string): LatLngLiteral | null {
  const parts = value.split(',').map(Number);
  if (parts.length !== 2) return null;
  return { lat: parts[0], lng: parts[1] };
}

export function formatLatLng({ lat, lng }: LatLngLiteral): string {
  return `${lat.toFixed(6)},${lng.toFixed(6)}`;
}
