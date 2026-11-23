import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { DomEvent, DomUtil, latLng, point as pixelPoint, type LatLngTuple } from 'leaflet';
import { useMap } from 'react-leaflet';
import styles from './NodeCardOverlay.module.css';

export function NodeCardOverlay({
  position: [latitude, longitude],
  children,
}: {
  position: LatLngTuple;
  children: ReactNode;
}) {
  const map = useMap();
  const anchorRef = useRef<HTMLSpanElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const anchor = anchorRef.current;
    const card = cardRef.current;
    if (!anchor || !card) return;

    const update = () => {
      const point = map.latLngToContainerPoint(latLng(latitude, longitude));
      const size = map.getSize();
      anchor.hidden = point.x < 0 || point.y < 0 || point.x > size.x || point.y > size.y;
      anchor.style.left = `${point.x}px`;
      anchor.style.top = `${point.y}px`;
      if (anchor.hidden) return;

      const gap = 12;
      const padding = 8;
      const { offsetWidth: width, offsetHeight: height } = card;
      const above = point.y - gap - height;
      const below = point.y + gap;
      const preferredTop = above >= padding || size.y - below < point.y - gap ? above : below;
      const x = Math.max(padding, Math.min(point.x - width / 2, size.x - width - padding));
      const y = Math.max(padding, Math.min(preferredTop, size.y - height - padding));
      DomUtil.setPosition(card, pixelPoint(x, y));
    };

    update();
    map.on('move zoom resize', update);
    const observer = new ResizeObserver(update);
    observer.observe(card);
    observer.observe(map.getContainer());
    return () => {
      map.off('move zoom resize', update);
      observer.disconnect();
    };
  }, [map, latitude, longitude]);

  useLayoutEffect(() => {
    const card = cardRef.current;
    if (!card) return;

    DomEvent.disableClickPropagation(card);
    DomEvent.disableScrollPropagation(card);
    return () => {
      DomEvent.off(card);
    };
  }, []);

  return createPortal(
    <div className={styles.layer}>
      <span ref={anchorRef} className={styles.anchor} aria-hidden="true" />
      <div ref={cardRef} className={styles.card}>
        {children}
      </div>
    </div>,
    map.getContainer()
  );
}
