import { memo, useId } from 'react';
import { formatInt, timeZoneName } from '../lib/format';
import { formatWeight, type WeightUnit } from '../lib/units';
import type { Interval, Place } from '../types';
import { InfoTip } from './InfoTip';
import { PlaceInput } from './PlaceInput';
import { Segmented } from './Segmented';

export type PlaceField = 'origin' | 'destination';

export interface TripFormValues {
  origin: Place | null;
  destination: Place | null;
  departure: string;
  /** Cargo weight as typed, in `loadUnit`, with thousands separators. */
  load: string;
}

export type TripFormErrors = Partial<Record<keyof TripFormValues, string>>;

interface Props {
  values: TripFormValues;
  errors: TripFormErrors;
  loadUnit: WeightUnit;
  interval: Interval;
  availableIntervals: Interval[];
  tareLb: number;
  submitting: boolean;
  /** Results on screen are for different trip details. */
  stale: boolean;
  minDeparture: string;
  maxDeparture: string;
  /** The field the map is waiting to fill after a press of its map button. */
  pickField: PlaceField | null;
  onChange: (patch: Partial<TripFormValues>) => void;
  onLoadUnitChange: (unit: WeightUnit) => void;
  onIntervalChange: (interval: Interval) => void;
  onPickToggle: (field: PlaceField) => void;
  onFocusPlace: (field: PlaceField) => void;
  onSubmit: () => void;
}

const INTERVAL_OPTIONS: { value: Interval; label: string }[] = [
  { value: '10', label: '10 mi' },
  { value: '25', label: '25 mi' },
  { value: '50', label: '50 mi' },
];

const UNIT_OPTIONS: { value: WeightUnit; label: string }[] = [
  { value: 'lb', label: 'lb' },
  { value: 'kg', label: 'kg' },
];

export const TripForm = memo(function TripForm(props: Props) {
  const { values, errors, interval, tareLb, submitting, loadUnit, onChange } = props;
  const departureId = useId();
  const loadId = useId();
  const loadHintId = useId();

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
          picking={props.pickField === 'origin'}
          onPickToggle={() => props.onPickToggle('origin')}
          onFocusField={() => props.onFocusPlace('origin')}
          onChange={(origin) => onChange({ origin })}
        />
        <button
          type="button"
          className="swap"
          aria-label="Swap origin and destination"
          title="Swap origin and destination"
          disabled={!values.origin && !values.destination}
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
          picking={props.pickField === 'destination'}
          onPickToggle={() => props.onPickToggle('destination')}
          onFocusField={() => props.onFocusPlace('destination')}
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
          <div className="field-label-row">
            <label htmlFor={loadId} className="field-label">
              Cargo weight
            </label>
            <InfoTip topic="cargo weight">
              Enter the freight only, not the truck. Heavier loads are rated more cautiously in strong wind: above{' '}
              {formatWeight(30000, loadUnit)}, wind of 45 to 54 mph is No travel, and above{' '}
              {formatWeight(40000, loadUnit)}, wind of 35 to 44 mph is Severe. Wind of 55 mph or more is No travel for
              any load.
            </InfoTip>
          </div>
          <div className={`input-affix${errors.load ? ' input-invalid' : ''}`}>
            <input
              id={loadId}
              className="input-bare"
              type="text"
              inputMode="numeric"
              autoComplete="off"
              placeholder={loadUnit === 'kg' ? '17,000' : '38,000'}
              value={values.load}
              aria-invalid={Boolean(errors.load)}
              aria-describedby={loadHintId}
              onChange={(e) => {
                const digits = e.target.value.replace(/[^\d]/g, '').slice(0, 6);
                onChange({ load: digits ? formatInt(Number(digits)) : '' });
              }}
            />
            <div className="affix affix-toggle">
              <Segmented
                label="Weight unit"
                size="inline"
                options={UNIT_OPTIONS}
                value={loadUnit}
                onChange={props.onLoadUnitChange}
              />
            </div>
          </div>
          {errors.load ? (
            <p id={loadHintId} className="field-error">
              {errors.load}
            </p>
          ) : (
            <p id={loadHintId} className="field-hint">
              Routing adds {formatWeight(tareLb, loadUnit)} for the empty truck and trailer
            </p>
          )}
        </div>
      </div>

      <div className="field">
        <div className="field-label-row">
          <span className="field-label">Weather checkpoints every</span>
          <InfoTip topic="weather checkpoints">
            How often the forecast is checked along each route, for the hour the truck should reach that point. Each
            checkpoint covers the stretch of road nearest to it, which is how Severe and High miles are counted. 10 mi
            catches local weather such as mountain passes; 50 mi is coarser. You can switch after the results load
            without searching again.
          </InfoTip>
        </div>
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
        ) : props.stale ? (
          'Update routes'
        ) : (
          'Find routes'
        )}
      </button>
    </form>
  );
});
