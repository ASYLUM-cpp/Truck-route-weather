import { memo, useState } from 'react';
import type { Checkpoint, Interval, PlanResponse } from '../types';
import { CheckpointTable } from './CheckpointTable';
import { RouteCard } from './RouteCard';

interface Props {
  plan: PlanResponse;
  interval: Interval;
  selectedId: string;
  onSelect: (id: string) => void;
  onFocusCheckpoint: (cp: Checkpoint) => void;
}

/** Memoized: the forecast slider re-renders the app every hour step, and this panel does not depend on it. */
export const RouteResults = memo(function RouteResults({
  plan,
  interval,
  selectedId,
  onSelect,
  onFocusCheckpoint,
}: Props) {
  const [showCheckpoints, setShowCheckpoints] = useState(false);
  const rec = plan.recommendations[interval];
  const recommended = plan.routes.find((r) => r.id === rec.route_id)!;
  const selected = plan.routes.find((r) => r.id === selectedId) ?? recommended;
  const checkpoints = selected.analyses[interval].checkpoints;

  return (
    <section className="results" aria-live="polite">
      <div className={`verdict${rec.all_routes_no_travel ? ' verdict-warning' : ''}`}>
        <p className="verdict-label">{rec.all_routes_no_travel ? 'Least exposed route' : 'Recommended route'}</p>
        <p className="verdict-route">
          {recommended.label}
          {recommended.via && <span className="verdict-via">via {recommended.via}</span>}
        </p>
        <p className="verdict-reason">{rec.reason}</p>
        {rec.all_routes_no_travel && (
          <p className="verdict-reason">
            Every route meets No travel conditions at this departure time. Consider leaving later.
          </p>
        )}
      </div>

      {plan.notices.map((n) => (
        <p key={n} className="notice">
          {n}
        </p>
      ))}

      <div className="route-list" role="group" aria-label="Route options">
        {plan.routes.map((route) => (
          <RouteCard
            key={route.id}
            route={route}
            interval={interval}
            recommended={route.id === rec.route_id}
            allRoutesNoTravel={rec.all_routes_no_travel}
            selected={route.id === selected.id}
            onSelect={() => onSelect(route.id)}
          />
        ))}
      </div>

      <div className="checkpoints">
        <button
          type="button"
          className="disclosure"
          aria-expanded={showCheckpoints}
          onClick={() => setShowCheckpoints((v) => !v)}
        >
          <svg className="disclosure-icon" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
            <path
              d="M4 2.5L7.5 6 4 9.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {checkpoints.length} checkpoints on {selected.label}
        </button>
        {showCheckpoints && <CheckpointTable checkpoints={checkpoints} onFocus={onFocusCheckpoint} />}
      </div>
    </section>
  );
});

export function ResultsSkeleton() {
  return (
    <div className="results" aria-hidden="true">
      <div className="skeleton skeleton-verdict" />
      {[0, 1, 2].map((i) => (
        <div key={i} className="skeleton skeleton-route" />
      ))}
    </div>
  );
}
