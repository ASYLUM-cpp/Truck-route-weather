import { formatInt } from './format';

export type WeightUnit = 'lb' | 'kg';

export const LB_PER_KG = 2.20462262;

/** Pounds from a value typed in the given unit. */
export function toLb(value: number, unit: WeightUnit): number {
  return unit === 'kg' ? value * LB_PER_KG : value;
}

/** A pound value in the given unit, rounded to a whole number for display and inputs. */
export function fromLb(lb: number, unit: WeightUnit): number {
  return Math.round(unit === 'kg' ? lb / LB_PER_KG : lb);
}

export function formatWeight(lb: number, unit: WeightUnit): string {
  return `${formatInt(fromLb(lb, unit))} ${unit}`;
}

/** The largest whole value in the unit that does not exceed a pound limit. */
export function maxInUnit(limitLb: number, unit: WeightUnit): number {
  return unit === 'kg' ? Math.floor(limitLb / LB_PER_KG) : limitLb;
}
