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
import { mapStyleUrl, type MapStyleId } from '../lib/mapStyles';
import { LEVEL_COLOR, UNKNOWN_COLOR, explainCheckpoint, levelColor, levelLabel } from '../lib/risk';
import type { Checkpoint, HeatmapResponse, Interval, LngLat, PlanResponse, Place } from '../types';
import { MapStyleSwitcher } from './MapStyleSwitcher';
import type { PlaceField } from './TripForm';

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
const FIELD_LABEL: Record<PlaceField, string> = { origin: 'From', destination: 'To' };
const MENU_SIZE = { width: 184, height: 92 };

export interface HeatOverlay {
  frame: string;
  bounds: HeatmapResponse['bounds'];
}

export interface MapFocus {
  routeId: string;
  checkpoint: Checkpoint;
  nonce: number;
}

/**
 * The form field the map will fill. `explicit` comes from the field's map button and makes a plain click
 * pick a point; otherwise the field was only focused while empty, and a right-click fills it.
 */
export interface MapPick {
  field: PlaceField;
  explicit: boolean;
}

export type PickSource = 'pick' | 'menu' | 'drag';

interface Props {
  plan: PlanResponse | null;
  interval: Interval;
  selectedId: string | null;
  onSelectRoute: (id: string) => void;
  heat: HeatOverlay | null;
  heatVisible: boolean;
  truck: LngLat | null;
  focus: MapFocus | null;
  /** Cargo weight as the user entered it, for checkpoint explanations. */
  cargoText: string;
  origin: Place | null;
  destination: Place | null;
  pick: MapPick | null;
  onPlacePicked: (field: PlaceField, lngLat: LngLat, source: PickSource) => void;
  onCancelPick: () => void;
  mapStyle: MapStyleId;
  onMapStyleChange: (id: MapStyleId) => void;
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

function popupHtml(routeLabel: string, cp: Checkpoint, cargoText: string): string {
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
      <p class="pp-note">${escapeHtml(explainCheckpoint(cp, cargoText))}</p>
    </div>`;
}

function applySelection(map: MLMap, selectedId: string | null) {
  const id = selectedId ?? '';
  map.setFilter('route-other', notSelected(id));
  map.setFilter('route-casing', isSelected(id));
  map.setFilter('route-selected', isSelected(id));
  map.setFilter('cp-other', notSelected(id));
  map.setFilter('cp-selected', isSelected(id));
}

function applyHeat(map: MLMap, heat: HeatOverlay | null, visible: boolean) {
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
  map.setLayoutProperty('heat', 'visibility', visible ? 'visible' : 'none');
}

function canHover(): boolean {
  return window.matchMedia('(hover: hover) and (pointer: fine)').matches;
}

export function MapView(props: Props) {
  const { plan, interval, selectedId, heat, heatVisible, truck, focus, origin, destination, pick, mapStyle } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const labelMarkers = useRef<Array<{ id: string; marker: maplibregl.Marker }>>([]);
  const truckMarker = useRef<maplibregl.Marker | null>(null);
  const endpointMarkers = useRef<Record<PlaceField, maplibregl.Marker | null>>({ origin: null, destination: null });
  // Route and checkpoint features, kept so they can be put back after the base map changes.
  const overlayData = useRef({ routes: EMPTY, checkpoints: EMPTY });
  const loadStyle = useRef<(id: MapStyleId) => void>(() => undefined);
  const shownStyle = useRef(mapStyle);
  const menuRef = useRef<HTMLDivElement>(null);
  // Map event handlers are bound once; they read the current props through this ref.
  const latest = useRef(props);
  useLayoutEffect(() => {
    latest.current = props;
  });
  const [ready, setReady] = useState(false);
  const [baseMapFailed, setBaseMapFailed] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number; lngLat: LngLat } | null>(null);

  // Create the map once.
  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current!,
      style: mapStyleUrl(latest.current.mapStyle),
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

    // Base map loading. A style that errors or stalls is replaced by a plain background so routes and
    // weather still render; picking another map type tries again.
    let settled = false;
    let usingFallback = false;
    let styleTimer = 0;
    const fallBack = () => {
      if (settled) return;
      settled = true;
      usingFallback = true;
      window.clearTimeout(styleTimer);
      setBaseMapFailed(true);
      map.setStyle(FALLBACK_STYLE, { diff: false });
    };
    const watchStyle = () => {
      settled = false;
      usingFallback = false;
      window.clearTimeout(styleTimer);
      styleTimer = window.setTimeout(fallBack, STYLE_TIMEOUT_MS);
    };
    loadStyle.current = (id) => {
      watchStyle();
      map.setStyle(mapStyleUrl(id), { diff: false });
    };
    watchStyle();
    // Only errors before a style finishes loading mean the style failed; later ones are single tiles.
    map.on('error', () => {
      if (!settled && !map.isStyleLoaded()) fallBack();
    });

    // Every style load, including a change of map type, starts without our layers; add them back.
    map.on('style.load', () => {
      if (!usingFallback) {
        settled = true;
        window.clearTimeout(styleTimer);
        setBaseMapFailed(false);
      }
      const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
      map.addSource('routes', { type: 'geojson', data: overlayData.current.routes });
      map.addSource('checkpoints', { type: 'geojson', data: overlayData.current.checkpoints });

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
      applySelection(map, latest.current.selectedId);
      applyHeat(map, latest.current.heat, latest.current.heatVisible);
      setReady(true);
    });

    const picking = () => latest.current.pick?.explicit === true;

    map.on('mouseenter', 'route-hit', () => {
      if (!picking()) map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', 'route-hit', () => (map.getCanvas().style.cursor = ''));
    map.on('click', 'route-hit', (e) => {
      if (picking()) return;
      const id = e.features?.[0]?.properties?.route as string | undefined;
      if (id) latest.current.onSelectRoute(id);
    });

    const showCheckpoint = (e: MapLayerMouseEvent) => {
      const f = e.features?.[0];
      const current = latest.current.plan;
      if (!f || !current || picking()) return;
      const route = current.routes.find((r) => r.id === f.properties.route);
      const cp = route?.analyses[latest.current.interval].checkpoints[f.properties.index as number];
      if (!route || !cp) return;
      map.getCanvas().style.cursor = 'pointer';
      popupRef
        .current!.setLngLat([cp.lon, cp.lat])
        .setHTML(popupHtml(route.label, cp, latest.current.cargoText))
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

    // Choosing places on the map: a click while a field's map button is on, or a right-click. A right-click
    // fills the field waiting for a place, and otherwise offers both fields.
    map.on('click', (e) => {
      setMenu(null);
      const current = latest.current.pick;
      if (current?.explicit) latest.current.onPlacePicked(current.field, [e.lngLat.lng, e.lngLat.lat], 'pick');
    });
    map.on('contextmenu', (e) => {
      e.originalEvent.preventDefault();
      const lngLat: LngLat = [e.lngLat.lng, e.lngLat.lat];
      const current = latest.current.pick;
      if (current) {
        setMenu(null);
        latest.current.onPlacePicked(current.field, lngLat, 'pick');
      } else {
        const box = map.getContainer();
        setMenu({
          x: Math.max(4, Math.min(e.point.x, box.clientWidth - MENU_SIZE.width - 4)),
          y: Math.max(4, Math.min(e.point.y, box.clientHeight - MENU_SIZE.height - 4)),
          lngLat,
        });
      }
    });
    map.on('movestart', () => setMenu(null));

    mapRef.current = map;
    return () => {
      window.clearTimeout(styleTimer);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Change of map type.
  useEffect(() => {
    if (!ready || shownStyle.current === mapStyle) return;
    shownStyle.current = mapStyle;
    loadStyle.current(mapStyle);
  }, [mapStyle, ready]);

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
    overlayData.current = {
      routes: { type: 'FeatureCollection', features: routeFeatures },
      checkpoints: { type: 'FeatureCollection', features: cpFeatures },
    };
    (map.getSource('routes') as GeoJSONSource | undefined)?.setData(overlayData.current.routes);
    (map.getSource('checkpoints') as GeoJSONSource | undefined)?.setData(overlayData.current.checkpoints);
  }, [plan, interval, ready]);

  // Route labels and framing when a new plan arrives.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    labelMarkers.current.forEach(({ marker }) => marker.remove());
    labelMarkers.current = [];
    if (!plan) return;

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
    applySelection(map, selectedId);
    labelMarkers.current.forEach(({ id: rid, marker }) =>
      marker.getElement().classList.toggle('is-selected', rid === selectedId),
    );
  }, [selectedId, plan, ready]);

  // Forecast overlay.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    applyHeat(map, heat, heatVisible);
  }, [heat, heatVisible, ready]);

  // From and To pins, which can be dragged to adjust the place.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    for (const field of ['origin', 'destination'] as const) {
      const place = field === 'origin' ? origin : destination;
      const existing = endpointMarkers.current[field];
      if (!place) {
        existing?.remove();
        endpointMarkers.current[field] = null;
        continue;
      }
      let marker = existing;
      if (!marker) {
        const el = document.createElement('div');
        el.className = `endpoint-pin endpoint-${field}`;
        const created = new maplibregl.Marker({ element: el, draggable: true });
        created.on('dragend', () => {
          const ll = created.getLngLat();
          latest.current.onPlacePicked(field, [ll.lng, ll.lat], 'drag');
        });
        marker = created.setLngLat([place.lon, place.lat]).addTo(map);
        endpointMarkers.current[field] = marker;
      } else {
        marker.setLngLat([place.lon, place.lat]);
      }
      const text = `${FIELD_LABEL[field]}: ${place.label}. Drag to move.`;
      marker.getElement().title = text;
      marker.getElement().setAttribute('aria-label', text);
    }
  }, [origin, destination, ready]);

  // Bring newly chosen places into view, but only when one is off screen, so picking on the map never
  // moves the map under the pointer.
  const originKey = origin ? `${origin.lat},${origin.lon}` : '';
  const destinationKey = destination ? `${destination.lat},${destination.lon}` : '';
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const { origin: o, destination: d } = latest.current;
    const points = [o, d].filter((p): p is Place => p !== null).map((p): LngLat => [p.lon, p.lat]);
    if (!points.length) return;
    const view = map.getBounds();
    if (points.every((p) => view.contains(p))) return;
    if (points.length === 1) {
      map.easeTo({ center: points[0], zoom: Math.max(map.getZoom(), 5), duration: 600 });
    } else {
      const narrow = (containerRef.current?.clientWidth ?? 1000) < 700;
      map.fitBounds(new maplibregl.LngLatBounds(points[0], points[0]).extend(points[1]), {
        padding: narrow ? 50 : 100,
        duration: 600,
        maxZoom: 9,
      });
    }
  }, [originKey, destinationKey, ready]);

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
      .setHTML(popupHtml(route.label, cp, latest.current.cargoText))
      .addTo(map);
  }, [focus, plan, ready]);

  // The right-click menu takes focus so Escape and the arrow keys work, and closes on any outside press.
  useEffect(() => {
    if (!menu) return;
    menuRef.current?.querySelector('button')?.focus({ preventScroll: true });
    const close = (e: PointerEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenu(null);
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [menu]);

  const showPickHint = pick && (pick.explicit || canHover());

  return (
    <>
      <div
        ref={containerRef}
        className={`map${pick?.explicit ? ' is-picking' : ''}`}
        role="region"
        aria-label="Route map. Right-click to set From or To."
      />
      <div className="map-top">
        {showPickHint && (
          <p className="map-hint" role="status">
            {pick.explicit
              ? `${canHover() ? 'Click' : 'Tap'} the map to set ${FIELD_LABEL[pick.field]}.`
              : `Right-click the map to set ${FIELD_LABEL[pick.field]}.`}
            {pick.explicit && (
              <button type="button" className="map-hint-cancel" onClick={props.onCancelPick}>
                Cancel
              </button>
            )}
          </p>
        )}
        {baseMapFailed && (
          <p className="map-notice" role="status">
            The base map could not load. Routes and weather are still shown.
          </p>
        )}
      </div>
      {menu && (
        <div
          ref={menuRef}
          className="map-menu"
          role="menu"
          aria-label="Use this place"
          style={{ left: menu.x, top: menu.y }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation();
              setMenu(null);
            } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
              e.preventDefault();
              const items = [...e.currentTarget.querySelectorAll('button')];
              const i = items.indexOf(document.activeElement as HTMLButtonElement);
              items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length]?.focus();
            }
          }}
        >
          {(['origin', 'destination'] as const).map((field) => (
            <button
              key={field}
              type="button"
              role="menuitem"
              className="map-menu-item"
              onClick={() => {
                props.onPlacePicked(field, menu.lngLat, 'menu');
                setMenu(null);
              }}
            >
              <span className={`menu-pin endpoint-${field}`} aria-hidden="true" />
              Set as {FIELD_LABEL[field]}
            </button>
          ))}
        </div>
      )}
      <MapStyleSwitcher value={mapStyle} onChange={props.onMapStyleChange} />
    </>
  );
}
