import type { HeatVariable, HeatmapResponse } from '../types';
import { LEVEL_COLOR, LEVELS } from './risk';

type RGB = [number, number, number];

interface ScaleVariable {
  label: string;
  unit: string;
  max: number;
  /** Thresholds from the risk table, drawn as ticks on the legend. */
  ticks: number[];
  light: RGB;
  dark: RGB;
  /** Values at or below this are treated as nothing and left transparent. Below ticks[0] is only tinted. */
  floor: number;
}

export const SCALE_VARIABLES: Record<Exclude<HeatVariable, 'risk'>, ScaleVariable> = {
  wind: {
    label: 'Wind',
    unit: 'mph',
    max: 60,
    ticks: [25, 35, 45, 55],
    light: [214, 226, 240],
    dark: [24, 52, 92],
    floor: 1,
  },
  rain: {
    label: 'Rain',
    unit: 'in/hr',
    max: 1,
    ticks: [0.1, 0.25, 0.5, 1],
    light: [205, 232, 242],
    dark: [10, 82, 112],
    floor: 0.005,
  },
  snow: {
    label: 'Snow',
    unit: 'in/hr',
    max: 3,
    ticks: [0.5, 1, 2, 3],
    light: [228, 220, 242],
    dark: [72, 42, 120],
    floor: 0.005,
  },
};

export const HEAT_VARIABLE_LABEL: Record<HeatVariable, string> = {
  risk: 'Risk',
  wind: 'Wind',
  rain: 'Rain',
  snow: 'Snow',
};

const RISK_ALPHA = [0.16, 0.42, 0.56, 0.68, 0.78];

function hexToRgb(hex: string): RGB {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const RISK_RGB = LEVELS.map((l) => hexToRgb(LEVEL_COLOR[l]));

export function scaleColor(variable: Exclude<HeatVariable, 'risk'>, value: number): [number, number, number, number] {
  const v = SCALE_VARIABLES[variable];
  if (value <= v.floor) return [...v.light, 0];
  const threshold = v.ticks[0];
  // Below the first risk threshold the weather is Low, so it gets only a faint tint. Otherwise a
  // 15 mph breeze reads as a storm on the map while every route is correctly rated Low.
  if (value < threshold) return [...v.light, 0.04 + 0.1 * (value / threshold)];
  const t = Math.min(1, (value - threshold) / (v.max - threshold));
  const k = 0.25 + 0.75 * Math.pow(t, 0.8);
  const rgb = v.light.map((c, i) => Math.round(c + (v.dark[i] - c) * k)) as RGB;
  return [...rgb, 0.38 + 0.5 * Math.pow(t, 0.7)];
}

function cellColor(variable: HeatVariable, value: number | null): [number, number, number, number] {
  if (value === null) return [0, 0, 0, 0];
  if (variable === 'risk') {
    const level = Math.max(0, Math.min(4, Math.round(value)));
    return [...RISK_RGB[level], RISK_ALPHA[level]];
  }
  return scaleColor(variable, value);
}

/**
 * One small PNG per forecast hour, one pixel per grid cell. The map stretches
 * the image over the corridor with linear filtering, which turns the coarse
 * grid into a smooth field without any work on the main thread while the
 * slider moves.
 */
export function renderFrames(heatmap: HeatmapResponse, variable: HeatVariable): string[] {
  const { nx, ny, cells, times, values } = heatmap;
  const canvas = document.createElement('canvas');
  canvas.width = nx;
  canvas.height = ny;
  const ctx = canvas.getContext('2d');
  if (!ctx) return [];
  const series = values[variable];
  const frames: string[] = [];
  for (let h = 0; h < times.length; h++) {
    const image = ctx.createImageData(nx, ny);
    for (let c = 0; c < cells.length; c++) {
      const [col, row] = cells[c];
      const [r, g, b, a] = cellColor(variable, series[c][h]);
      const p = (row * nx + col) * 4;
      image.data[p] = r;
      image.data[p + 1] = g;
      image.data[p + 2] = b;
      image.data[p + 3] = Math.round(a * 255);
    }
    ctx.putImageData(image, 0, 0);
    frames.push(canvas.toDataURL('image/png'));
  }
  return frames;
}

export function rgba([r, g, b, a]: [number, number, number, number]): string {
  return `rgba(${r}, ${g}, ${b}, ${a.toFixed(2)})`;
}
