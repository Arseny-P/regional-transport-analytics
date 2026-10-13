import { useEffect, useState } from 'react';
import type { LatLngLiteral } from 'leaflet';
import { Marker, Polygon, useMapEvents } from 'react-leaflet';
import { bboxFromPoints, formatLatLng, parseLatLng, type BBox } from '@/entities/area';

interface SelectAreaProps {
  onChange: (area: BBox | null) => void;
  point1: string;
  point2: string;
  setPoint1: (value: string) => void;
  setPoint2: (value: string) => void;
}

export function SelectArea({ onChange, point1, point2, setPoint1, setPoint2 }: SelectAreaProps) {
  const [points, setPoints] = useState<LatLngLiteral[]>([]);

  useEffect(() => {
    if (!point1 || !point2) {
      setPoints([]);
      onChange(null);
      return;
    }

    const p1 = parseLatLng(point1);
    const p2 = parseLatLng(point2);
    if (p1 && p2) {
      setPoints([p1, p2]);
      onChange(bboxFromPoints(p1, p2));
    }
  }, [point1, point2, onChange]);

  useMapEvents({
    click(e) {
      if (points.length < 2) {
        const newPoints = [...points, e.latlng];
        setPoints(newPoints);

        if (newPoints.length === 2) {
          const [p1, p2] = newPoints;
          onChange(bboxFromPoints(p1, p2));
          setPoint1(formatLatLng(p1));
          setPoint2(formatLatLng(p2));
        }
      } else {
        setPoints([e.latlng]);
        onChange(null);
        setPoint1('');
        setPoint2('');
      }
    },
  });

  return (
    <>
      {points.map((p, idx) => (
        <Marker key={idx} position={p} />
      ))}

      {points.length === 2 && (
        <Polygon
          positions={[
            [points[0].lat, points[0].lng],
            [points[0].lat, points[1].lng],
            [points[1].lat, points[1].lng],
            [points[1].lat, points[0].lng],
            [points[0].lat, points[0].lng],
          ]}
        />
      )}
    </>
  );
}
