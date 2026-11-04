export type LevelKey = 'low' | 'moderate' | 'high' | 'severe' | 'no_travel';
export type Interval = '10' | '25' | '50';
export type HeatVariable = 'risk' | 'wind' | 'rain' | 'snow';
export type LngLat = [number, number];

export interface Place {
  label: string;
  detail: string;
  lat: number;
  lon: number;
}

export interface Checkpoint {
  mile: number;
  lat: number;
  lon: number;
  eta: string;
  wind_mph: number | null;
  gust_mph: number | null;
  rain_in: number | null;
  snow_in: number | null;
  level: LevelKey | null;
  drivers: Array<'wind' | 'rain' | 'snow'>;
  load_rule: string | null;
}

export type Segment = [fromMi: number, toMi: number, level: LevelKey | null];

export interface RouteAnalysis {
  checkpoints: Checkpoint[];
  segments: Segment[];
  miles_by_level: Record<LevelKey | 'unknown', number>;
  avg_risk: number | null;
}

export interface Route {
  id: string;
  label: string;
  via: string | null;
  distance_mi: number;
  duration_s: number;
  traffic_delay_s: number;
  departure: string;
  arrival: string;
  coordinates: LngLat[];
  coordinate_miles: number[];
  /** [hours since departure, lon, lat, mile] every 15 minutes */
  positions: Array<[number, number, number, number]>;
  analyses: Record<Interval, RouteAnalysis>;
}

export interface Recommendation {
  route_id: string;
  ranking: string[];
  reason: string;
  all_routes_no_travel: boolean;
}

export interface PlanResponse {
  departure: string;
  load_lb: number;
  gross_weight_lb: number;
  /** Spacings computed for this plan. Very long trips may omit 10 mi. */
  intervals: Interval[];
  routes: Route[];
  recommendations: Record<Interval, Recommendation>;
  notices: string[];
}

export interface HeatmapResponse {
  bounds: { west: number; east: number; north: number; south: number };
  nx: number;
  ny: number;
  cells: Array<[col: number, row: number]>;
  times: string[];
  values: Record<HeatVariable, Array<Array<number | null>>>;
}

export interface AppConfig {
  truck_tare_lb: number;
  max_load_lb: number;
  max_departure_days: number;
}
