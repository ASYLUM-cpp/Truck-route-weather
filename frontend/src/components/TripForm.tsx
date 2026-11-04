import { memo, useId } from 'react';
import { formatInt, timeZoneName } from '../lib/format';
import type { Interval, Place } from '../types';
import { PlaceInput } from './PlaceInput';
import { Segmented } from './Segmented';

export interface TripFormValues {
  origin: Place | null;
  destination: Place | null;
  departure: string;
  load: string;
}

export type TripFormErrors = Partial<Record<keyof TripFormValues, string>>;

interface Props {
  values: TripFormValues;
  errors: TripFormErrors;
  interval: Interval;
  availableIntervals: Interval[];
  tareLb: number;
  submitting: boolean;
  minDeparture: string;
  maxDeparture: string;
  onChange: (patch: Partial<TripFormValues>) => void;
  onIntervalChange: (interval: Interval) => void;
  onSubmit: () => void;
}

const INTERVAL_OPTIONS: { value: Interval; label: string }[] = [
  { value: '10', label: '10 mi' },
  { value: '25', label: '25 mi' },
  { value: '50', label: '50 mi' },
];

export const TripForm = memo(function TripForm(props: Props) {
  const { values, errors, interval, tareLb, submitting, onChange } = props;
  const departureId = useId();
  const loadId = useId();

  return (
    <form
      className="trip-form"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        props.onSubmit();
      }}
    >
      <div className="endpoints">
        <PlaceInput
          label="From"
          placeholder="City, address or place"
          value={values.origin}
          error={errors.origin}
          onChange={(origin) => onChange({ origin })}
        />
        <button
          type="button"
          className="swap"
          aria-label="Swap origin and destination"
          title="Swap origin and destination"
          onClick={() => onChange({ origin: values.destination, destination: values.origin })}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M5 2v11M5 13l-2.5-2.5M5 13l2.5-2.5M11 14V3M11 3L8.5 5.5M11 3l2.5 2.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        <PlaceInput
          label="To"
          placeholder="City, address or place"
          value={values.destination}
          error={errors.destination}
          onChange={(destination) => onChange({ destination })}
        />
      </div>

      <div className="field-row">
        <div className="field">
          <label htmlFor={departureId} className="field-label">
            Departure
          </label>
          <input
            id={departureId}
            className={`input${errors.departure ? ' input-invalid' : ''}`}
            type="datetime-local"
            value={values.departure}
            min={props.minDeparture}
            max={props.maxDeparture}
            aria-invalid={Boolean(errors.departure)}
            onChange={(e) => onChange({ departure: e.target.value })}
          />
          {errors.departure ? (
            <p className="field-error">{errors.departure}</p>
          ) : (
            <p className="field-hint">Your time zone ({timeZoneName()})</p>
          )}
        </div>

        <div className="field field-load">
          <label htmlFor={loadId} className="field-label">
            Cargo weight
          </label>
          <div className={`input-affix${errors.load ? ' input-invalid' : ''}`}>
            <input
              id={loadId}
              className="input-bare"
              type="text"
              inputMode="numeric"
              placeholder="38,000"
              value={values.load}
              aria-invalid={Boolean(errors.load)}
              onChange={(e) => {
                const digits = e.target.value.replace(/[^\d]/g, '').slice(0, 6);
                onChange({ load: digits ? formatInt(Number(digits)) : '' });
              }}
            />
            <span className="affix">lb</span>
          </div>
          {errors.load ? (
            <p className="field-error">{errors.load}</p>
          ) : (
            <p className="field-hint">Routing adds {formatInt(tareLb)} lb for truck and trailer</p>
          )}
        </div>
      </div>

      <div className="field">
        <span className="field-label">Weather checkpoints every</span>
        <Segmented
          label="Weather checkpoints every"
          options={INTERVAL_OPTIONS.map((o) => ({
            ...o,
            disabled: !props.availableIntervals.includes(o.value),
            hint: 'Not available for a trip this long. Plan a shorter trip to use 10-mile spacing.',
          }))}
          value={interval}
          onChange={props.onIntervalChange}
        />
      </div>

      <button type="submit" className="button-primary" disabled={submitting}>
        {submitting ? (
          <>
            <span className="button-spinner" aria-hidden="true" />
            Finding routes
          </>
        ) : (
          'Find routes'
        )}
      </button>
    </form>
  );
});
