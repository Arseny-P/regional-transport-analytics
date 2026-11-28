import { useMemo, type ReactNode } from 'react';
import { divIcon, type LatLngTuple, type LeafletEventHandlerFnMap } from 'leaflet';
import { Marker } from 'react-leaflet';
import { railNodeLabel } from '../config/graphStyles';
import type { RailNodeKind } from '../model/types';
import styles from './RailNodeMarker.module.css';

interface RailNodeMarkerProps {
  position: LatLngTuple;
  kind?: RailNodeKind;
  color: string;
  selected: boolean;
  eventHandlers?: LeafletEventHandlerFnMap;
  children: ReactNode;
}

export function RailNodeMarker({
  position,
  kind,
  color,
  selected,
  eventHandlers,
  children,
}: RailNodeMarkerProps) {
  const icon = useMemo(() => {
    const symbol = document.createElement('span');
    symbol.className = styles.symbol;
    if (kind) symbol.dataset.kind = kind;
    if (selected) symbol.dataset.selected = '';
    symbol.style.color = color;
    const size = selected ? 20 : 14;
    return divIcon({ className: '', html: symbol, iconSize: [size, size] });
  }, [color, kind, selected]);

  return (
    <Marker
      position={position}
      icon={icon}
      title={railNodeLabel(kind)}
      zIndexOffset={selected ? 1000 : 0}
      eventHandlers={eventHandlers}
    >
      {children}
    </Marker>
  );
}
