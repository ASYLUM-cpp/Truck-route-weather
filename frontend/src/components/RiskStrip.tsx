import { levelColor, levelLabel } from '../lib/risk';
import type { Segment } from '../types';

interface Props {
  segments: Segment[];
  totalMiles: number;
}

/** The whole trip as one horizontal band, coloured by risk level mile by mile. */
export function RiskStrip({ segments, totalMiles }: Props) {
  const summary = segments
    .map(([from, to, level]) => `${levelLabel(level)} from mile ${Math.round(from)} to ${Math.round(to)}`)
    .join('; ');
  return (
    <div className="risk-strip" role="img" aria-label={`Risk along the route: ${summary}`}>
      {segments.map(([from, to, level]) => (
        <span
          key={`${from}-${to}`}
          className="risk-strip-part"
          style={{ flexGrow: Math.max(to - from, 0.001), background: levelColor(level) }}
          title={`${levelLabel(level)}, mile ${Math.round(from)} to ${Math.round(to)}`}
        />
      ))}
      <span className="visually-hidden">{Math.round(totalMiles)} miles</span>
    </div>
  );
}
