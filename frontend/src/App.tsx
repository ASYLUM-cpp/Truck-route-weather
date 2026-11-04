import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { MapView, type MapFocus, type MapPick, type PickSource } from './components/MapView';
import { ResultsSkeleton, RouteResults } from './components/RouteResults';
import { RouteLegend } from './components/RouteLegend';
import { TripForm, type PlaceField, type TripFormErrors, type TripFormValues } from './components/TripForm';
import { WeatherBar } from './components/WeatherBar';
import { ApiError, api } from './lib/api';
import { formatInt, formatTime, nextFullHour, toLocalInputValue } from './lib/format';
import { positionAt, thin } from './lib/geo';
import { renderFrames } from './lib/heatmap';
import { MAP_STYLE_IDS, type MapStyleId } from './lib/mapStyles';
import { readPref, writePref } from './lib/prefs';
import { formatWeight, fromLb, maxInUnit, toLb, type WeightUnit } from './lib/units';
import type {
  AppConfig,
  Checkpoint,
  HeatVariable,
  HeatmapResponse,
  Interval,
  LngLat,
  PlanResponse,
  Place,
} from './types';

const ALL_INTERVALS: Interval[] = ['10', '25', '50'];

/** The spacing to show: the user's choice when the plan has it, otherwise the closest computed one. */
function effectiveInterval(chosen: Interval, plan: PlanResponse | null): Interval {
  if (!plan || plan.intervals.includes(chosen)) return chosen;
  return plan.intervals[0];
}

const DEFAULT_CONFIG: AppConfig = { truck_tare_lb: 35000, max_load_lb: 80000, max_departure_days: 7 };
const DEPARTURE_GRACE_MS = 10 * 60 * 1000;
const SLOW_REQUEST_MS = 6000;
const MIN_TRIP_MI = 1;
const NARROW_QUERY = '(max-width: 900px)';

const EXAMPLE_TRIP = {
  origin: { label: 'Denver, CO', detail: 'Colorado, United States', lat: 39.7392, lon: -104.9903 },
  destination: { label: 'Salt Lake City, UT', detail: 'Utah, United States', lat: 40.7608, lon: -111.891 },
  loadLb: 42000,
};

/** The typed cargo weight as a number in the unit it was typed in. */
function parseLoad(text: string): number {
  return Number(text.replace(/[^\d]/g, ''));
}

function loadInLb(values: TripFormValues, unit: WeightUnit): number {
  return Math.round(toLb(parseLoad(values.load), unit));
}

function distanceMi(a: Place, b: Place): number {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 3958.8 * Math.asin(Math.sqrt(h));
}

/** A place for a point picked on the map, named by its coordinates until the address lookup answers. */
function pinnedPlace([lon, lat]: LngLat): Place {
  return { label: `${lat.toFixed(4)}, ${lon.toFixed(4)}`, detail: 'Point on the map', lat, lon };
}

interface PlannedTrip {
  origin: Place;
  destination: Place;
  departure: string;
  loadLb: number;
}

/** Whether the form still describes the trip whose results are on screen. */
function sameTrip(trip: PlannedTrip, values: TripFormValues, unit: WeightUnit): boolean {
  const samePlace = (a: Place | null, b: Place) => a !== null && a.lat === b.lat && a.lon === b.lon;
  if (!samePlace(values.origin, trip.origin) || !samePlace(values.destination, trip.destination)) return false;
  if (!values.departure || new Date(values.departure).toISOString() !== trip.departure) return false;
  // Switching lb and kg rounds the typed value, so allow for a pound or two of rounding.
  return Math.abs(loadInLb(values, unit) - trip.loadLb) <= 2.5;
}

function validate(values: TripFormValues, config: AppConfig, unit: WeightUnit): TripFormErrors {
  const errors: TripFormErrors = {};
  if (!values.origin) errors.origin = 'Choose a starting point from the suggestions or the map.';
  if (!values.destination) errors.destination = 'Choose a destination from the suggestions or the map.';
  if (values.origin && values.destination && distanceMi(values.origin, values.destination) < MIN_TRIP_MI)
    errors.destination = 'From and To are the same place. Choose a destination at least 1 mile away.';
  if (!values.departure) {
    errors.departure = 'Enter a departure time.';
  } else {
    const t = new Date(values.departure).getTime();
    if (t < Date.now() - DEPARTURE_GRACE_MS) errors.departure = 'Departure time is in the past.';
    else if (t > Date.now() + config.max_departure_days * 864e5)
      errors.departure = `Choose a time within the next ${config.max_departure_days} days.`;
  }
  if (!values.load) errors.load = 'Enter the cargo weight. Use 0 for an empty trailer.';
  else if (parseLoad(values.load) > maxInUnit(config.max_load_lb, unit))
    errors.load = `Cargo weight cannot exceed ${formatInt(maxInUnit(config.max_load_lb, unit))} ${unit}.`;
  return errors;
}

const SERVER_FIELD_MAP: Record<string, keyof TripFormValues> = {
  origin: 'origin',
  'origin.lat': 'origin',
  'origin.lon': 'origin',
  destination: 'destination',
  'destination.lat': 'destination',
  'destination.lon': 'destination',
  departure: 'departure',
  load_lb: 'load',
};

export function App() {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const [values, setValues] = useState<TripFormValues>(() => ({
    origin: null,
    destination: null,
    departure: toLocalInputValue(nextFullHour()),
    load: '',
  }));
  const [errors, setErrors] = useState<TripFormErrors>({});
  const [loadUnit, setLoadUnit] = useState<WeightUnit>(() => readPref('loadUnit', ['lb', 'kg'], 'lb'));
  const [mapStyle, setMapStyle] = useState<MapStyleId>(() => readPref('mapStyle', MAP_STYLE_IDS, 'light'));
  const [pick, setPick] = useState<MapPick | null>(null);
  const valuesRef = useRef(values);
  useEffect(() => {
    valuesRef.current = values;
  }, [values]);
  const [interval, setIntervalMi] = useState<Interval>('25');
  // Read when a plan arrives, so a spacing change made during the request is respected.
  const intervalRef = useRef(interval);

  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [plannedTrip, setPlannedTrip] = useState<PlannedTrip | null>(null);
  const [planStatus, setPlanStatus] = useState<'idle' | 'loading'>('idle');
  const [planError, setPlanError] = useState<string | null>(null);
  const [planSlow, setPlanSlow] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const userPickedRoute = useRef(false);
  const [focus, setFocus] = useState<MapFocus | null>(null);

  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null);
  const [heatStatus, setHeatStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [heatVariable, setHeatVariable] = useState<HeatVariable>('risk');
  const [heatHour, setHeatHour] = useState(0);
  const [heatVisible, setHeatVisible] = useState(true);
  const [playing, setPlaying] = useState(false);
  const heatAbort = useRef<AbortController | null>(null);
  const mapAreaRef = useRef<HTMLElement>(null);

  useEffect(() => {
    api
      .config()
      .then(setConfig)
      .catch(() => undefined);
  }, []);

  const updateValues = useCallback((patch: Partial<TripFormValues>) => {
    setValues((v) => ({ ...v, ...patch }));
    setErrors((e) => {
      const next = { ...e };
      for (const key of Object.keys(patch) as Array<keyof TripFormValues>) delete next[key];
      if ('origin' in patch && 'destination' in patch) {
        delete next.origin;
        delete next.destination;
      }
      return next;
    });
  }, []);

  /** Form edits; choosing a place for the field the map was waiting on ends the map pick. */
  const changeFromForm = useCallback(
    (patch: Partial<TripFormValues>) => {
      updateValues(patch);
      setPick((p) => (p && patch[p.field] ? null : p));
    },
    [updateValues],
  );

  const changeLoadUnit = useCallback(
    (unit: WeightUnit) => {
      if (unit === loadUnit) return;
      // Convert what was typed so the weight stays the same.
      setValues((v) => (v.load ? { ...v, load: formatInt(fromLb(toLb(parseLoad(v.load), loadUnit), unit)) } : v));
      setErrors((e) => {
        const next = { ...e };
        delete next.load;
        return next;
      });
      setLoadUnit(unit);
      writePref('loadUnit', unit);
    },
    [loadUnit],
  );

  const changeMapStyle = useCallback((id: MapStyleId) => {
    setMapStyle(id);
    writePref('mapStyle', id);
  }, []);

  const togglePick = useCallback((field: PlaceField) => {
    setPick((p) => (p?.explicit && p.field === field ? null : { field, explicit: true }));
    // On small screens the map is above the form; bring it into view to pick.
    if (window.matchMedia(NARROW_QUERY).matches) {
      const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      document.querySelector('.map-area')?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
    }
  }, []);

  const focusPlace = useCallback((field: PlaceField) => {
    setPick((p) => (p?.field === field ? p : { field, explicit: false }));
  }, []);

  const placePicked = useCallback(
    (field: PlaceField, lngLat: LngLat, source: PickSource) => {
      const place = pinnedPlace(lngLat);
      updateValues(field === 'origin' ? { origin: place } : { destination: place });
      if (source === 'pick') {
        // Move on to the other field when it is still empty, so two picks set a whole trip.
        const other: PlaceField = field === 'origin' ? 'destination' : 'origin';
        const next = valuesRef.current[other] ? null : other;
        setPick((p) => (next && p ? { field: next, explicit: p.explicit } : null));
        if (!next && window.matchMedia(NARROW_QUERY).matches) {
          document.querySelector('.trip-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }
      api
        .reverse(place.lat, place.lon)
        .then((found) => {
          if (!found) return;
          // Keep the pin where it was dropped, and ignore answers for a pin that has since moved.
          setValues((v) => {
            const current = v[field];
            if (!current || current.lat !== place.lat || current.lon !== place.lon) return v;
            return { ...v, [field]: { ...found, lat: place.lat, lon: place.lon } };
          });
        })
        .catch(() => undefined);
    },
    [updateValues],
  );

  // A map pick ends with Escape or when focus moves to another control in the panel.
  useEffect(() => {
    const onFocusIn = (e: FocusEvent) => {
      const target = e.target as Element | null;
      if (target?.closest('.panel') && !target.closest('[data-place-field]')) setPick(null);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPick(null);
    };
    document.addEventListener('focusin', onFocusIn);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('focusin', onFocusIn);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  const loadHeatmap = useCallback((p: PlanResponse) => {
    heatAbort.current?.abort();
    const controller = new AbortController();
    heatAbort.current = controller;
    setHeatStatus('loading');
    setHeatmap(null);
    setHeatHour(0);
    setPlaying(false);
    api
      .heatmap(
        { paths: p.routes.map((r) => thin(r.coordinates, 1500)), departure: p.departure, load_lb: p.load_lb },
        controller.signal,
      )
      .then((hm) => {
        setHeatmap(hm);
        setHeatStatus('ready');
      })
      .catch((err) => {
        if ((err as Error).name !== 'AbortError') setHeatStatus('error');
      });
  }, []);

  const submit = useCallback(async () => {
    const found = validate(values, config, loadUnit);
    setErrors(found);
    setPick(null);
    if (Object.keys(found).length) return;

    const trip: PlannedTrip = {
      origin: values.origin!,
      destination: values.destination!,
      departure: new Date(values.departure).toISOString(),
      loadLb: loadInLb(values, loadUnit),
    };

    heatAbort.current?.abort();
    setPlan(null);
    setHeatmap(null);
    setFocus(null);
    setPlanError(null);
    setPlanStatus('loading');
    setPlanSlow(false);
    const slowTimer = window.setTimeout(() => setPlanSlow(true), SLOW_REQUEST_MS);
    try {
      const result = await api.plan({
        origin: { lat: trip.origin.lat, lon: trip.origin.lon },
        destination: { lat: trip.destination.lat, lon: trip.destination.lon },
        departure: trip.departure,
        load_lb: trip.loadLb,
      });
      userPickedRoute.current = false;
      setPlan(result);
      setPlannedTrip(trip);
      setSelectedId(result.recommendations[effectiveInterval(intervalRef.current, result)].route_id);
      loadHeatmap(result);
      // On small screens the map sits above the form; bring it back into view to show the routes.
      if (window.matchMedia(NARROW_QUERY).matches) {
        const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        mapAreaRef.current?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
      }
    } catch (err) {
      const apiErr = err instanceof ApiError ? err : null;
      const fieldErrors: TripFormErrors = {};
      for (const [field, message] of Object.entries(apiErr?.fields ?? {})) {
        const key = SERVER_FIELD_MAP[field];
        if (key) fieldErrors[key] = message;
      }
      if (Object.keys(fieldErrors).length) setErrors(fieldErrors);
      else setPlanError(apiErr?.message ?? 'Something went wrong. Try again.');
    } finally {
      window.clearTimeout(slowTimer);
      setPlanStatus('idle');
    }
  }, [values, config, loadUnit, loadHeatmap]);

  const changeInterval = useCallback(
    (next: Interval) => {
      intervalRef.current = next;
      setIntervalMi(next);
      if (plan && !userPickedRoute.current) setSelectedId(plan.recommendations[next].route_id);
    },
    [plan],
  );

  const selectRoute = useCallback((id: string) => {
    userPickedRoute.current = true;
    setSelectedId(id);
  }, []);

  const focusCheckpoint = useCallback(
    (cp: Checkpoint) => {
      if (selectedId) setFocus({ routeId: selectedId, checkpoint: cp, nonce: Date.now() });
    },
    [selectedId],
  );

  function loadExample() {
    setPick(null);
    updateValues({
      origin: EXAMPLE_TRIP.origin,
      destination: EXAMPLE_TRIP.destination,
      load: formatInt(fromLb(EXAMPLE_TRIP.loadLb, loadUnit)),
      departure: toLocalInputValue(nextFullHour()),
    });
  }

  // Forecast frames are rendered once per data set and layer, so moving the slider only swaps an image.
  const frames = useMemo(() => (heatmap ? renderFrames(heatmap, heatVariable) : []), [heatmap, heatVariable]);
  const heat = useMemo(
    () => (heatmap && frames[heatHour] ? { frame: frames[heatHour], bounds: heatmap.bounds } : null),
    [heatmap, frames, heatHour],
  );

  const shownInterval = effectiveInterval(interval, plan);
  const selectedRoute = plan?.routes.find((r) => r.id === selectedId) ?? null;
  const frameTime = heatmap?.times[heatHour] ?? null;
  const truck = useMemo(() => {
    if (!plan || !selectedRoute || !frameTime || heatStatus !== 'ready') return null;
    const hours = (Date.parse(frameTime) - Date.parse(plan.departure)) / 3.6e6;
    const { lngLat, mile } = positionAt(selectedRoute.positions, hours);
    let note: string;
    if (hours < 0) note = `${selectedRoute.label} departs at ${formatTime(plan.departure)}`;
    else if (hours * 3600 >= selectedRoute.duration_s) note = `${selectedRoute.label} has arrived`;
    else if (mile < 1) note = `${selectedRoute.label} is setting off`;
    else note = `${selectedRoute.label} is near mile ${Math.round(mile)}`;
    return { lngLat, note };
  }, [plan, selectedRoute, frameTime, heatStatus]);

  const stale = Boolean(plan && plannedTrip && !sameTrip(plannedTrip, values, loadUnit));
  // Only a field that is empty, or whose map button is on, takes a place from a right-click.
  const activePick = pick && (pick.explicit || !values[pick.field]) ? pick : null;
  const cargoText = plan ? formatWeight(plan.load_lb, loadUnit) : '';

  const now = new Date();
  const minDeparture = toLocalInputValue(now);
  const maxDeparture = toLocalInputValue(new Date(now.getTime() + config.max_departure_days * 864e5));

  return (
    <div className={`app${plan ? ' has-plan' : ''}`}>
      <aside className="panel">
        <header className="panel-header">
          <h1 className="brand">
            <svg className="brand-mark" width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
              <rect width="32" height="32" rx="7" fill="currentColor" />
              <path
                d="M8 23 L14 9 L18 9 L24 23"
                fill="none"
                stroke="#fff"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path d="M16 12v2M16 17v2" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            </svg>
            Truck Route Weather
          </h1>
        </header>

        <div className="panel-body">
          <TripForm
            values={values}
            errors={errors}
            loadUnit={loadUnit}
            interval={shownInterval}
            availableIntervals={plan?.intervals ?? ALL_INTERVALS}
            tareLb={config.truck_tare_lb}
            submitting={planStatus === 'loading'}
            stale={stale}
            minDeparture={minDeparture}
            maxDeparture={maxDeparture}
            pickField={pick?.explicit ? pick.field : null}
            onChange={changeFromForm}
            onLoadUnitChange={changeLoadUnit}
            onIntervalChange={changeInterval}
            onPickToggle={togglePick}
            onFocusPlace={focusPlace}
            onSubmit={submit}
          />

          {planError && (
            <div className="alert" role="alert">
              {planError}
            </div>
          )}

          {planStatus === 'loading' ? (
            <>
              {planSlow && (
                <p className="notice notice-slow" role="status">
                  Still working. The first trip after a quiet period can take up to a minute while the server starts.
                </p>
              )}
              <ResultsSkeleton />
            </>
          ) : plan && selectedId ? (
            <>
              {stale && (
                <p className="notice notice-stale" role="status">
                  The trip details have changed. Press Update routes to see results for them.
                </p>
              )}
              <RouteResults
                plan={plan}
                interval={shownInterval}
                selectedId={selectedId}
                onSelect={selectRoute}
                onFocusCheckpoint={focusCheckpoint}
              />
            </>
          ) : (
            !planError && (
              <div className="empty">
                <p>
                  Compare three truck routes by the weather each one meets. The forecast is checked at every checkpoint
                  for the hour the truck reaches it.
                </p>
                <p className="empty-tip">
                  You can also choose From and To on the map: press the target button in either field, or right-click
                  the map. Drag a pin to adjust it.
                </p>
                <button type="button" className="link-button" onClick={loadExample}>
                  Fill in an example trip: Denver to Salt Lake City
                </button>
              </div>
            )
          )}
        </div>

        <footer className="panel-footer">
          Truck routing by{' '}
          <a href="https://www.tomtom.com" target="_blank" rel="noreferrer">
            TomTom
          </a>
          . Forecasts by{' '}
          <a href="https://open-meteo.com" target="_blank" rel="noreferrer">
            Open-Meteo
          </a>
          .
        </footer>
      </aside>

      <main className="map-area" ref={mapAreaRef}>
        <MapView
          plan={plan}
          interval={shownInterval}
          selectedId={selectedId}
          onSelectRoute={selectRoute}
          heat={heat}
          heatVisible={heatVisible}
          truck={truck?.lngLat ?? null}
          focus={focus}
          cargoText={cargoText}
          origin={values.origin}
          destination={values.destination}
          pick={activePick}
          onPlacePicked={placePicked}
          onCancelPick={() => setPick(null)}
          mapStyle={mapStyle}
          onMapStyleChange={changeMapStyle}
        />
        <RouteLegend showEndpoints={Boolean(values.origin || values.destination)} />
        {plan && (
          <WeatherBar
            status={heatStatus}
            visible={heatVisible}
            variable={heatVariable}
            hour={heatHour}
            maxHour={heatmap ? heatmap.times.length - 1 : 48}
            frameTime={frameTime}
            truckNote={truck?.note ?? null}
            playing={playing}
            onVisibleChange={setHeatVisible}
            onVariableChange={setHeatVariable}
            onHourChange={setHeatHour}
            onPlayingChange={setPlaying}
            onRetry={() => loadHeatmap(plan)}
          />
        )}
      </main>
    </div>
  );
}
