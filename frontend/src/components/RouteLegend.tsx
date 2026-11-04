import { LEVELS, LEVEL_COLOR, LEVEL_LABEL, UNKNOWN_COLOR } from '../lib/risk';

export function RouteLegend() {
  return (
    <div className="map-legend" aria-label="Route risk colours">
      <p className="map-legend-title">Route risk</p>
      <ul>
        {LEVELS.map((l) => (
          <li key={l}>
            <span className="swatch swatch-line" style={{ background: LEVEL_COLOR[l] }} />
            {LEVEL_LABEL[l]}
          </li>
        ))}
        <li>
          <span className="swatch swatch-line" style={{ background: UNKNOWN_COLOR }} />
          No data
        </li>
      </ul>
    </div>
  );
}
