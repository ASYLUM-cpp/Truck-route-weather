import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { MapView, type MapFocus } from './components/MapView';
import { ResultsSkeleton, RouteResults } from './components/RouteResults';
import { RouteLegend } from './components/RouteLegend';
import { TripForm, type TripFormErrors, type TripFormValues } from './components/TripForm';
import { WeatherBar } from './components/WeatherBar';
import { ApiError, api } from './lib/api';
import { formatInt, formatTime, nextFullHour, toLocalInputValue } from './lib/format';
import { positionAt, thin } from './lib/geo';
import { renderFrames } from './lib/heatmap';
import type { AppConfig, Checkpoint, HeatVariable, HeatmapResponse, Interval, PlanResponse } from './types';

const ALL_INTERVALS: Interval[] = ['10', '25', '50'];

/** The spacing to show: the user's choice when the plan has it, otherwise the closest computed one. */
function effectiveInterval(chosen: Interval, plan: PlanResponse | null): Interval {
  if (!plan || plan.intervals.includes(chosen)) return chosen;
  return plan.intervals[0];
}

const DEFAULT_CONFIG: AppConfig = { truck_tare_lb: 35000, max_load_lb: 80000, max_departure_days: 7 };
const DEPARTURE_GRACE_MS = 10 * 60 * 1000;
const SLOW_REQUEST_MS = 6000;

const EXAMPLE_TRIP: Omit<TripFormValues, 'departure'> = {
  origin: { label: 'Denver, CO', detail: 'Colorado, United States', lat: 39.7392, lon: -104.9903 },
  destination: { label: 'Salt Lake City, UT', detail: 'Utah, United States', lat: 40.7608, lon: -111.891 },
  load: formatInt(42000),
};

function parseLoad(text: string): number {
  return Number(text.replace(/[^\d]/g, ''));
}

function validate(values: TripFormValues, config: AppConfig): TripFormErrors {
  const errors: TripFormErrors = {};
  if (!values.origin) errors.origin = 'Choose a starting point from the suggestions.';
  if (!values.destination) errors.destination = 'Choose a destination from the suggestions.';
  if (!values.departure) {
    errors.departure = 'Enter a departure time.';
  } else {
    const t = new Date(values.departure).getTime();
    if (t < Date.now() - DEPARTURE_GRACE_MS) errors.departure = 'Departure time is in the past.';
    else if (t > Date.now() + config.max_departure_days * 864e5)
      errors.departure = `Choose a time within the next ${config.max_departure_days} days.`;
  }
  if (!values.load) errors.load = 'Enter the cargo weight.';
  else if (parseLoad(values.load) > config.max_load_lb)
    errors.load = `Cargo weight cannot exceed ${formatInt(config.max_load_lb)} lb.`;
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
  const [interval, setIntervalMi] = useState<Interval>('25');
  // Read when a plan arrives, so a spacing change made during the request is respected.
  const intervalRef = useRef(interval);

  const [plan, setPlan] = useState<PlanResponse | null>(null);
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
    const found = validate(values, config);
    setErrors(found);
    if (Object.keys(found).length) return;

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
        origin: { lat: values.origin!.lat, lon: values.origin!.lon },
        destination: { lat: values.destination!.lat, lon: values.destination!.lon },
        departure: new Date(values.departure).toISOString(),
        load_lb: parseLoad(values.load),
      });
      userPickedRoute.current = false;
      setPlan(result);
      setSelectedId(result.recommendations[effectiveInterval(intervalRef.current, result)].route_id);
      loadHeatmap(result);
      // On small screens the map sits above the form; bring it back into view to show the routes.
      if (window.matchMedia('(max-width: 900px)').matches) {
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
  }, [values, config, loadHeatmap]);

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
    updateValues({ ...EXAMPLE_TRIP, departure: toLocalInputValue(nextFullHour()) });
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
            interval={shownInterval}
            availableIntervals={plan?.intervals ?? ALL_INTERVALS}
            tareLb={config.truck_tare_lb}
            submitting={planStatus === 'loading'}
            minDeparture={minDeparture}
            maxDeparture={maxDeparture}
            onChange={updateValues}
            onIntervalChange={changeInterval}
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
            <RouteResults
              plan={plan}
              interval={shownInterval}
              selectedId={selectedId}
              onSelect={selectRoute}
              onFocusCheckpoint={focusCheckpoint}
            />
          ) : (
            !planError && (
              <div className="empty">
                <p>
                  Compare three truck routes by the weather each one meets. The forecast is checked at every checkpoint
                  for the hour the truck reaches it.
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
        />
        <RouteLegend />
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
