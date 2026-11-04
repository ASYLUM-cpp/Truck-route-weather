import { LEVELS, LEVEL_COLOR, LEVEL_LABEL, UNKNOWN_COLOR } from '../lib/risk';

export function RouteLegend({ showEndpoints }: { showEndpoints: boolean }) {
  return (
    <div className="map-legend" aria-label="Map key">
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
      {showEndpoints && (
        <ul className="map-legend-endpoints">
          <li>
            <span className="menu-pin endpoint-origin" aria-hidden="true" />
            From
          </li>
          <li>
            <span className="menu-pin endpoint-destination" aria-hidden="true" />
            To
          </li>
        </ul>
      )}
    </div>
  );
}
