import { useEffect, useId } from 'react';
import { formatDateTime, formatTime } from '../lib/format';
import { HEAT_VARIABLE_LABEL, SCALE_VARIABLES, rgba, scaleColor } from '../lib/heatmap';
import { LEVELS, LEVEL_COLOR, LEVEL_LABEL } from '../lib/risk';
import type { HeatVariable } from '../types';
import { InfoTip } from './InfoTip';
import { Segmented } from './Segmented';

interface Props {
  status: 'loading' | 'ready' | 'error';
  visible: boolean;
  variable: HeatVariable;
  hour: number;
  maxHour: number;
  frameTime: string | null;
  truckNote: string | null;
  playing: boolean;
  onVisibleChange: (v: boolean) => void;
  onVariableChange: (v: HeatVariable) => void;
  onHourChange: (h: number) => void;
  onPlayingChange: (p: boolean) => void;
  onRetry: () => void;
}

const VARIABLE_OPTIONS = (Object.keys(HEAT_VARIABLE_LABEL) as HeatVariable[]).map((v) => ({
  value: v,
  label: HEAT_VARIABLE_LABEL[v],
}));

const PLAY_STEP_MS = 650;

export function WeatherBar(props: Props) {
  const { status, visible, variable, hour, maxHour, playing } = props;
  const sliderId = useId();
  const ready = status === 'ready';

  const { onHourChange } = props;
  useEffect(() => {
    if (!playing || !ready) return;
    const timer = window.setTimeout(() => onHourChange(hour >= maxHour ? 0 : hour + 1), PLAY_STEP_MS);
    return () => window.clearTimeout(timer);
  }, [playing, ready, hour, maxHour, onHourChange]);

  return (
    <div className="weather-bar" role="region" aria-label="Weather forecast layer">
      <div className="weather-row">
        <label className="switch">
          <input
            type="checkbox"
            checked={visible}
            onChange={(e) => props.onVisibleChange(e.target.checked)}
            disabled={!ready}
          />
          <span className="switch-track" aria-hidden="true" />
          <span className="switch-label">Forecast</span>
        </label>
        <InfoTip topic="the corridor forecast" placement="top">
          Weather across the whole trip area for the 48 hours after departure. Drag the slider or press play to move
          through time, and choose overall risk, wind, rain or snow. The blue dot shows where the selected route&rsquo;s
          truck would be at that hour. Ticks on the scale mark the risk thresholds.
        </InfoTip>

        <Segmented
          label="Forecast layer"
          size="small"
          options={VARIABLE_OPTIONS}
          value={variable}
          onChange={props.onVariableChange}
        />

        {status === 'loading' && <span className="weather-status">Loading forecast for the corridor</span>}
        {status === 'error' && (
          <span className="weather-status">
            Forecast layer unavailable.{' '}
            <button type="button" className="link-button" onClick={props.onRetry}>
              Retry
            </button>
          </span>
        )}
      </div>

      <div className="weather-row weather-time">
        <button
          type="button"
          className="icon-button"
          aria-label={playing ? 'Pause forecast animation' : 'Play forecast animation'}
          onClick={() => props.onPlayingChange(!playing)}
          disabled={!ready}
        >
          {playing ? (
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <rect x="3" y="2" width="3" height="10" rx="1" fill="currentColor" />
              <rect x="8" y="2" width="3" height="10" rx="1" fill="currentColor" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <path
                d="M4 2.2v9.6a.6.6 0 0 0 .9.5l7.6-4.8a.6.6 0 0 0 0-1L4.9 1.7a.6.6 0 0 0-.9.5z"
                fill="currentColor"
              />
            </svg>
          )}
        </button>
        <label htmlFor={sliderId} className="visually-hidden">
          Hours after departure
        </label>
        <input
          id={sliderId}
          className="slider"
          type="range"
          min={0}
          max={maxHour}
          step={1}
          value={hour}
          disabled={!ready}
          aria-valuetext={
            props.frameTime ? `${formatDateTime(props.frameTime)}, ${hour} hours after departure` : undefined
          }
          onChange={(e) => {
            props.onPlayingChange(false);
            props.onHourChange(Number(e.target.value));
          }}
          style={{ '--fill': `${maxHour > 0 ? (hour / maxHour) * 100 : 0}%` } as React.CSSProperties}
        />
        <span className="weather-clock">
          <span className="weather-clock-time">{props.frameTime ? formatTime(props.frameTime) : 'Departure'}</span>
          <span className="weather-clock-offset">{hour === 0 ? 'Departure hour' : `+${hour} h`}</span>
        </span>
      </div>

      <div className="weather-row weather-legend">
        <Legend variable={variable} />
        {props.truckNote && <span className="truck-note">{props.truckNote}</span>}
      </div>
    </div>
  );
}

function Legend({ variable }: { variable: HeatVariable }) {
  if (variable === 'risk') {
    return (
      <ul className="legend-swatches" aria-label="Risk levels">
        {LEVELS.map((l) => (
          <li key={l}>
            <span className="swatch" style={{ background: LEVEL_COLOR[l] }} />
            {LEVEL_LABEL[l]}
          </li>
        ))}
      </ul>
    );
  }
  const v = SCALE_VARIABLES[variable];
  const stops = Array.from({ length: 11 }, (_, i) => {
    const value = (i / 10) * v.max;
    return `${rgba(scaleColor(variable, Math.max(value, v.floor * 1.01)))} ${i * 10}%`;
  });
  return (
    <div className="legend-scale" aria-label={`${v.label} scale in ${v.unit}, with risk thresholds marked`}>
      <div className="legend-bar">
        <div className="legend-ramp" style={{ background: `linear-gradient(to right, ${stops.join(', ')})` }}>
          {v.ticks.map((t) => (
            <span key={t} className="legend-tick" style={{ left: `${(t / v.max) * 100}%` }} />
          ))}
        </div>
        <div className="legend-labels" aria-hidden="true">
          <span style={{ left: '0%' }}>0</span>
          {v.ticks.map((t) => (
            <span key={t} style={{ left: `${(t / v.max) * 100}%` }}>
              {t}
            </span>
          ))}
        </div>
      </div>
      <span className="legend-unit">{v.unit}</span>
    </div>
  );
}
