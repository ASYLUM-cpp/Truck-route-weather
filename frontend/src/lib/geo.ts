import type { LngLat } from '../types';

function upperIndex(values: number[], x: number): number {
  let lo = 0;
  let hi = values.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (values[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function pointAtMile(coords: LngLat[], miles: number[], mile: number): LngLat {
  if (mile <= miles[0]) return coords[0];
  if (mile >= miles[miles.length - 1]) return coords[coords.length - 1];
  const i = upperIndex(miles, mile);
  const span = miles[i] - miles[i - 1];
  const t = span === 0 ? 0 : (mile - miles[i - 1]) / span;
  const [x0, y0] = coords[i - 1];
  const [x1, y1] = coords[i];
  return [x0 + (x1 - x0) * t, y0 + (y1 - y0) * t];
}

/** Part of a polyline between two distances along it. */
export function sliceByMiles(coords: LngLat[], miles: number[], from: number, to: number): LngLat[] {
  const out: LngLat[] = [pointAtMile(coords, miles, from)];
  for (let i = upperIndex(miles, from); i < coords.length && miles[i] < to; i++) {
    if (miles[i] > from) out.push(coords[i]);
  }
  out.push(pointAtMile(coords, miles, to));
  return out;
}

export function thin<T>(items: T[], max: number): T[] {
  if (items.length <= max) return items;
  const step = (items.length - 1) / (max - 1);
  return Array.from({ length: max }, (_, k) => items[Math.round(k * step)]);
}

/** Truck position at a number of hours after departure. */
export function positionAt(
  positions: Array<[number, number, number, number]>,
  hours: number,
): { lngLat: LngLat; mile: number } {
  if (hours <= positions[0][0]) return { lngLat: [positions[0][1], positions[0][2]], mile: 0 };
  const last = positions[positions.length - 1];
  if (hours >= last[0]) return { lngLat: [last[1], last[2]], mile: last[3] };
  const i = upperIndex(
    positions.map((p) => p[0]),
    hours,
  );
  const a = positions[i - 1];
  const b = positions[i];
  const t = (hours - a[0]) / (b[0] - a[0]);
  return {
    lngLat: [a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t],
    mile: a[3] + (b[3] - a[3]) * t,
  };
}
