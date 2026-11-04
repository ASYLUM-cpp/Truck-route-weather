import maplibregl, {
  type ExpressionSpecification,
  type GeoJSONSource,
  type ImageSource,
  type Map as MLMap,
  type MapLayerMouseEvent,
  type StyleSpecification,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { formatTime } from '../lib/format';
import { pointAtMile, sliceByMiles } from '../lib/geo';
import { LEVEL_COLOR, UNKNOWN_COLOR, explainCheckpoint, levelColor, levelLabel } from '../lib/risk';
import type { Checkpoint, HeatmapResponse, Interval, LngLat, PlanResponse } from '../types';

const STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL || 'https://tiles.openfreemap.org/styles/positron';
const STYLE_TIMEOUT_MS = 10000;
/** Used when the base map can't load, so routes and weather still render. */
const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e9ecef' } }],
};
const INITIAL_CENTER: LngLat = [-97, 39];
const INITIAL_ZOOM = 3.3;
const LABEL_POSITIONS = [0.32, 0.5, 0.68];

export interface HeatOverlay {
  frame: string;
  bounds: HeatmapResponse['bounds'];
}

export interface MapFocus {
  routeId: string;
  checkpoint: Checkpoint;
  nonce: number;
}

interface Props {
  plan: PlanResponse | null;
  interval: Interval;
  selectedId: string | null;
  onSelectRoute: (id: string) => void;
  heat: HeatOverlay | null;
  heatVisible: boolean;
  truck: LngLat | null;
  focus: MapFocus | null;
}

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

const LEVEL_COLOR_EXPR: ExpressionSpecification = [
  'match',
  ['get', 'level'],
  'low',
  LEVEL_COLOR.low,
  'moderate',
  LEVEL_COLOR.moderate,
  'high',
  LEVEL_COLOR.high,
  'severe',
  LEVEL_COLOR.severe,
  'no_travel',
  LEVEL_COLOR.no_travel,
  UNKNOWN_COLOR,
];

function isSelected(id: string): ExpressionSpecification {
  return ['==', ['get', 'route'], id];
}
function notSelected(id: string): ExpressionSpecification {
  return ['!=', ['get', 'route'], id];
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function popupHtml(routeLabel: string, cp: Checkpoint, loadLb: number): string {
  const n = (v: number | null, d: number, unit: string) => (v === null ? 'n/a' : `${v.toFixed(d)} ${unit}`);
  const wind =
    cp.wind_mph === null
      ? 'n/a'
      : `${cp.wind_mph.toFixed(1)} mph${cp.gust_mph !== null ? `, gusts ${Math.round(cp.gust_mph)}` : ''}`;
  return `
    <div class="pp">
      <div class="pp-head">
        <span class="pp-title">${escapeHtml(routeLabel)}, mile ${Math.round(cp.mile)}</span>
        <span class="pp-level"><span class="level-dot" style="background:${levelColor(cp.level)}"></span>${escapeHtml(levelLabel(cp.level))}</span>
      </div>
      <dl class="pp-grid">
        <dt>Arrives</dt><dd>${escapeHtml(formatTime(cp.eta))}</dd>
        <dt>Wind</dt><dd>${escapeHtml(wind)}</dd>
        <dt>Rain</dt><dd>${n(cp.rain_in, 2, 'in/hr')}</dd>
        <dt>Snow</dt><dd>${n(cp.snow_in, 2, 'in/hr')}</dd>
      </dl>
      <p class="pp-note">${escapeHtml(explainCheckpoint(cp, loadLb))}</p>
    </div>`;
}

export function MapView(props: Props) {
  const { plan, interval, selectedId, heat, heatVisible, truck, focus } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const labelMarkers = useRef<Array<{ id: string; marker: maplibregl.Marker }>>([]);
  const truckMarker = useRef<maplibregl.Marker | null>(null);
  // Map event handlers are bound once; they read the current props through this ref.
  const latest = useRef(props);
  useLayoutEffect(() => {
    latest.current = props;
  });
  const [ready, setReady] = useState(false);
  const [baseMapFailed, setBaseMapFailed] = useState(false);

  // Create the map once.
  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current!,
      style: STYLE_URL,
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    popupRef.current = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 12,
      maxWidth: '280px',
      className: 'cp-popup',
    });

    let loaded = false;
    let fellBack = false;
    const fallBack = () => {
      if (loaded || fellBack) return;
      fellBack = true;
      setBaseMapFailed(true);
      map.setStyle(FALLBACK_STYLE);
    };
    // Only errors before the first load mean the style itself failed; later ones are single tiles.
    map.on('error', () => {
      if (!map.isStyleLoaded()) fallBack();
    });
    const styleTimer = window.setTimeout(fallBack, STYLE_TIMEOUT_MS);

    map.on('load', () => {
      loaded = true;
      window.clearTimeout(styleTimer);
      const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
      map.addSource('routes', { type: 'geojson', data: EMPTY });
      map.addSource('checkpoints', { type: 'geojson', data: EMPTY });
      map.addSource('endpoints', { type: 'geojson', data: EMPTY });

      const lineLayout = { 'line-join': 'round', 'line-cap': 'round' } as const;
      map.addLayer(
        {
          id: 'route-other',
          type: 'line',
          source: 'routes',
          layout: lineLayout,
          paint: {
            'line-color': LEVEL_COLOR_EXPR,
            'line-width': ['interpolate', ['linear'], ['zoom'], 4, 2.5, 10, 4],
            'line-opacity': 0.55,
          },
        },
        firstLabel,
      );
      map.addLayer(
        {
          id: 'route-casing',
          type: 'line',
          source: 'routes',
          layout: lineLayout,
          filter: isSelected(''),
          paint: {
            'line-color': '#ffffff',
            'line-width': ['interpolate', ['linear'], ['zoom'], 4, 7, 10, 11],
          },
        },
        firstLabel,
      );
      map.addLayer(
        {
          id: 'route-selected',
          type: 'line',
          source: 'routes',
          layout: lineLayout,
          filter: isSelected(''),
          paint: {
            'line-color': LEVEL_COLOR_EXPR,
            'line-width': ['interpolate', ['linear'], ['zoom'], 4, 4, 10, 6.5],
          },
        },
        firstLabel,
      );
      map.addLayer({
        id: 'route-hit',
        type: 'line',
        source: 'routes',
        paint: { 'line-color': '#000000', 'line-opacity': 0, 'line-width': 16 },
      });
      map.addLayer({
        id: 'cp-other',
        type: 'circle',
        source: 'checkpoints',
        minzoom: 5,
        paint: {
          'circle-radius': 3,
          'circle-color': LEVEL_COLOR_EXPR,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1,
          'circle-opacity': 0.7,
          'circle-stroke-opacity': 0.7,
        },
      });
      map.addLayer({
        id: 'cp-selected',
        type: 'circle',
        source: 'checkpoints',
        filter: isSelected(''),
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 3.5, 10, 6.5],
          'circle-color': LEVEL_COLOR_EXPR,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1.5,
        },
      });
      map.addLayer({
        id: 'endpoints',
        type: 'circle',
        source: 'endpoints',
        paint: {
          'circle-radius': 6.5,
          'circle-color': ['match', ['get', 'kind'], 'origin', '#ffffff', '#18222F'],
          'circle-stroke-color': ['match', ['get', 'kind'], 'origin', '#18222F', '#ffffff'],
          'circle-stroke-width': 2.5,
        },
      });

      map.on('mouseenter', 'route-hit', () => (map.getCanvas().style.cursor = 'pointer'));
      map.on('mouseleave', 'route-hit', () => (map.getCanvas().style.cursor = ''));
      map.on('click', 'route-hit', (e) => {
        const id = e.features?.[0]?.properties?.route as string | undefined;
        if (id) latest.current.onSelectRoute(id);
      });

      const showCheckpoint = (e: MapLayerMouseEvent) => {
        const f = e.features?.[0];
        const current = latest.current.plan;
        if (!f || !current) return;
        const route = current.routes.find((r) => r.id === f.properties.route);
        const cp = route?.analyses[latest.current.interval].checkpoints[f.properties.index as number];
        if (!route || !cp) return;
        map.getCanvas().style.cursor = 'pointer';
        popupRef
          .current!.setLngLat([cp.lon, cp.lat])
          .setHTML(popupHtml(route.label, cp, current.load_lb))
          .addTo(map);
      };
      const hideCheckpoint = () => {
        map.getCanvas().style.cursor = '';
        popupRef.current!.remove();
      };
      for (const layer of ['cp-selected', 'cp-other']) {
        map.on('mousemove', layer, showCheckpoint);
        map.on('click', layer, showCheckpoint);
        map.on('mouseleave', layer, hideCheckpoint);
      }

      setReady(true);
    });

    mapRef.current = map;
    return () => {
      window.clearTimeout(styleTimer);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Route geometry and checkpoints for the active spacing.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    popupRef.current?.remove();
    const routeFeatures: GeoJSON.Feature[] = [];
    const cpFeatures: GeoJSON.Feature[] = [];
    for (const route of plan?.routes ?? []) {
      const analysis = route.analyses[interval];
      for (const [from, to, level] of analysis.segments) {
        routeFeatures.push({
          type: 'Feature',
          properties: { route: route.id, level: level ?? 'unknown' },
          geometry: {
            type: 'LineString',
            coordinates: sliceByMiles(route.coordinates, route.coordinate_miles, from, to),
          },
        });
      }
      analysis.checkpoints.forEach((cp, index) => {
        cpFeatures.push({
          type: 'Feature',
          properties: { route: route.id, index, level: cp.level ?? 'unknown' },
          geometry: { type: 'Point', coordinates: [cp.lon, cp.lat] },
        });
      });
    }
    (map.getSource('routes') as GeoJSONSource).setData({ type: 'FeatureCollection', features: routeFeatures });
    (map.getSource('checkpoints') as GeoJSONSource).setData({ type: 'FeatureCollection', features: cpFeatures });
  }, [plan, interval, ready]);

  // Endpoints, route labels and framing when a new plan arrives.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    labelMarkers.current.forEach(({ marker }) => marker.remove());
    labelMarkers.current = [];
    const endpoints = map.getSource('endpoints') as GeoJSONSource;
    if (!plan) {
      endpoints.setData(EMPTY);
      return;
    }
    const first = plan.routes[0];
    endpoints.setData({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: { kind: 'origin' },
          geometry: { type: 'Point', coordinates: first.coordinates[0] },
        },
        {
          type: 'Feature',
          properties: { kind: 'destination' },
          geometry: { type: 'Point', coordinates: first.coordinates[first.coordinates.length - 1] },
        },
      ],
    });

    plan.routes.forEach((route, i) => {
      const el = document.createElement('button');
      el.type = 'button';
      el.className = 'route-tag';
      el.textContent = route.id;
      el.setAttribute('aria-label', `Select ${route.label}`);
      el.addEventListener('click', (ev) => {
        ev.stopPropagation();
        latest.current.onSelectRoute(route.id);
      });
      const total = route.coordinate_miles[route.coordinate_miles.length - 1];
      const at = pointAtMile(route.coordinates, route.coordinate_miles, total * LABEL_POSITIONS[i % 3]);
      labelMarkers.current.push({
        id: route.id,
        marker: new maplibregl.Marker({ element: el }).setLngLat(at).addTo(map),
      });
    });

    const bounds = new maplibregl.LngLatBounds();
    plan.routes.forEach((r) => r.coordinates.forEach((c) => bounds.extend(c)));
    const narrow = (containerRef.current?.clientWidth ?? 1000) < 700;
    map.fitBounds(bounds, {
      padding: narrow ? { top: 40, right: 30, bottom: 200, left: 30 } : { top: 60, right: 60, bottom: 190, left: 60 },
      duration: 700,
      maxZoom: 11,
    });
  }, [plan, ready]);

  // Selection.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const id = selectedId ?? '';
    map.setFilter('route-other', notSelected(id));
    map.setFilter('route-casing', isSelected(id));
    map.setFilter('route-selected', isSelected(id));
    map.setFilter('cp-other', notSelected(id));
    map.setFilter('cp-selected', isSelected(id));
    labelMarkers.current.forEach(({ id: rid, marker }) =>
      marker.getElement().classList.toggle('is-selected', rid === selectedId),
    );
  }, [selectedId, plan, ready]);

  // Forecast overlay.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource('heat') as ImageSource | undefined;
    if (!heat) {
      if (map.getLayer('heat')) map.removeLayer('heat');
      if (source) map.removeSource('heat');
      return;
    }
    const { west, east, north, south } = heat.bounds;
    const coordinates: [LngLat, LngLat, LngLat, LngLat] = [
      [west, north],
      [east, north],
      [east, south],
      [west, south],
    ];
    if (source) {
      source.updateImage({ url: heat.frame, coordinates });
    } else {
      map.addSource('heat', { type: 'image', url: heat.frame, coordinates });
      map.addLayer(
        {
          id: 'heat',
          type: 'raster',
          source: 'heat',
          paint: { 'raster-opacity': 0.9, 'raster-resampling': 'linear', 'raster-fade-duration': 0 },
        },
        'route-other',
      );
    }
    map.setLayoutProperty('heat', 'visibility', heatVisible ? 'visible' : 'none');
  }, [heat, heatVisible, ready]);

  // Where the selected truck is at the forecast hour.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (!truck) {
      truckMarker.current?.remove();
      truckMarker.current = null;
      return;
    }
    if (!truckMarker.current) {
      const el = document.createElement('div');
      el.className = 'truck-marker';
      el.setAttribute('aria-hidden', 'true');
      truckMarker.current = new maplibregl.Marker({ element: el }).setLngLat(truck).addTo(map);
    } else {
      truckMarker.current.setLngLat(truck);
    }
  }, [truck, ready]);

  // Fly to a checkpoint picked in the table.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !focus || !plan) return;
    const route = plan.routes.find((r) => r.id === focus.routeId);
    if (!route) return;
    const { checkpoint: cp } = focus;
    map.flyTo({ center: [cp.lon, cp.lat], zoom: Math.max(map.getZoom(), 8), duration: 800 });
    popupRef
      .current!.setLngLat([cp.lon, cp.lat])
      .setHTML(popupHtml(route.label, cp, plan.load_lb))
      .addTo(map);
  }, [focus, plan, ready]);

  return (
    <>
      <div ref={containerRef} className="map" role="region" aria-label="Route map" />
      {baseMapFailed && (
        <p className="map-notice" role="status">
          The base map could not load. Routes and weather are still shown.
        </p>
      )}
    </>
  );
}
