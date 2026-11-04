export type MapStyleId = 'light' | 'streets' | 'dark';

export interface MapStyleOption {
  id: MapStyleId;
  label: string;
  url: string;
  /** Two colours for the small preview in the map type menu. */
  preview: [string, string];
}

const BASE = 'https://tiles.openfreemap.org/styles';

/** Basemaps hosted by OpenFreeMap. VITE_MAP_STYLE_URL, when set, replaces the light map. */
export const MAP_STYLES: MapStyleOption[] = [
  {
    id: 'light',
    label: 'Light',
    url: import.meta.env.VITE_MAP_STYLE_URL || `${BASE}/positron`,
    preview: ['#f2f3f0', '#d4dadc'],
  },
  { id: 'streets', label: 'Streets', url: `${BASE}/liberty`, preview: ['#f8f4f0', '#a7cfa0'] },
  { id: 'dark', label: 'Dark', url: `${BASE}/dark`, preview: ['#2b2d31', '#4a4e57'] },
];

export const MAP_STYLE_IDS = MAP_STYLES.map((s) => s.id);

export function mapStyleUrl(id: MapStyleId): string {
  return (MAP_STYLES.find((s) => s.id === id) ?? MAP_STYLES[0]).url;
}
