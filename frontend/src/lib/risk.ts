import type { Checkpoint, LevelKey } from '../types';

export const LEVELS: LevelKey[] = ['low', 'moderate', 'high', 'severe', 'no_travel'];

export const LEVEL_LABEL: Record<LevelKey, string> = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  severe: 'Severe',
  no_travel: 'No travel',
};

export const LEVEL_COLOR: Record<LevelKey, string> = {
  low: '#4A9460',
  moderate: '#D9A520',
  high: '#E2762B',
  severe: '#C8382E',
  no_travel: '#6B1D2E',
};

export const UNKNOWN_COLOR = '#A7B0BC';

export function levelColor(level: LevelKey | null): string {
  return level ? LEVEL_COLOR[level] : UNKNOWN_COLOR;
}

export function levelLabel(level: LevelKey | null): string {
  return level ? LEVEL_LABEL[level] : 'No data';
}

/** One sentence saying what sets the risk level at a checkpoint. `cargo` is the load as shown, e.g. "42,000 lb". */
export function explainCheckpoint(cp: Checkpoint, cargo: string): string {
  if (cp.level === null) return 'No forecast is available for this time.';
  if (cp.level === 'low') return 'All conditions are within normal limits.';
  const parts = cp.drivers.map((d) => {
    if (d === 'wind') {
      const base = `wind ${cp.wind_mph} mph`;
      return cp.load_rule ? `${base} with ${cargo} of cargo` : base;
    }
    if (d === 'rain') return `rain ${cp.rain_in?.toFixed(2)} in/hr`;
    return `snow ${cp.snow_in?.toFixed(2)} in/hr`;
  });
  const text = parts.join(' and ');
  return `${LEVEL_LABEL[cp.level]} because of ${text}.`;
}
