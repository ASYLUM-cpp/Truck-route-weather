import { formatDuration, formatMiles, formatTime } from '../lib/format';
import type { Interval, Route } from '../types';
import { RiskStrip } from './RiskStrip';

interface Props {
  route: Route;
  interval: Interval;
  recommended: boolean;
  /** Every route crosses No travel conditions, so the best one is only the least exposed. */
  allRoutesNoTravel: boolean;
  selected: boolean;
  onSelect: () => void;
}

export function RouteCard({ route, interval, recommended, allRoutesNoTravel, selected, onSelect }: Props) {
  const analysis = route.analyses[interval];
  const miles = analysis.miles_by_level;
  const notAdvised = miles.no_travel > 0.05;

  return (
    <button
      type="button"
      className={`route${selected ? ' is-selected' : ''}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="route-head">
        <span className="route-letter" aria-hidden="true">
          {route.id}
        </span>
        <span className="route-title">
          <span className="route-name">
            {route.label}
            {recommended && (
              <span className="tag tag-recommended">{allRoutesNoTravel ? 'Least exposed' : 'Recommended'}</span>
            )}
            {notAdvised && <span className="tag tag-warning">Not advised</span>}
          </span>
          <span className="route-via" title={route.via ? `via ${route.via}` : undefined}>
            {route.via ? `via ${route.via}` : 'Truck route'}
          </span>
        </span>
        <span className="route-time">
          <span className="route-duration">{formatDuration(route.duration_s)}</span>
          <span className="route-meta">{formatMiles(route.distance_mi)}</span>
          <span className="route-meta">Arrives {formatTime(route.arrival)}</span>
        </span>
      </span>

      <RiskStrip segments={analysis.segments} totalMiles={route.distance_mi} />

      <span className="route-stats">
        {notAdvised && (
          <span className="stat">
            <span className="stat-label">No travel</span>
            <span className="stat-value">{formatMiles(miles.no_travel)}</span>
          </span>
        )}
        <span className="stat">
          <span className="stat-label">Severe</span>
          <span className="stat-value">{formatMiles(miles.severe)}</span>
        </span>
        <span className="stat">
          <span className="stat-label">High</span>
          <span className="stat-value">{formatMiles(miles.high)}</span>
        </span>
        <span className="stat">
          <span className="stat-label">Average risk</span>
          <span className="stat-value">{analysis.avg_risk === null ? 'n/a' : analysis.avg_risk.toFixed(2)}</span>
        </span>
      </span>
    </button>
  );
}
