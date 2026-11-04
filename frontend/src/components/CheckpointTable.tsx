import { formatTime } from '../lib/format';
import { levelColor, levelLabel } from '../lib/risk';
import type { Checkpoint } from '../types';

interface Props {
  checkpoints: Checkpoint[];
  onFocus: (cp: Checkpoint) => void;
}

function fmt(value: number | null, digits: number): string {
  return value === null ? 'n/a' : value.toFixed(digits);
}

export function CheckpointTable({ checkpoints, onFocus }: Props) {
  return (
    <div className="table-wrap">
      <table className="cp-table">
        <thead>
          <tr>
            <th scope="col">Mile</th>
            <th scope="col">ETA</th>
            <th scope="col" className="num">
              Wind <span className="unit">mph</span>
            </th>
            <th scope="col" className="num">
              Rain <span className="unit">in/hr</span>
            </th>
            <th scope="col" className="num">
              Snow <span className="unit">in/hr</span>
            </th>
            <th scope="col">Risk</th>
          </tr>
        </thead>
        <tbody>
          {checkpoints.map((cp) => (
            <tr
              key={cp.mile}
              tabIndex={0}
              onClick={() => onFocus(cp)}
              onKeyDown={(e) => e.key === 'Enter' && onFocus(cp)}
            >
              <td className="num">{Math.round(cp.mile)}</td>
              <td>{formatTime(cp.eta)}</td>
              <td className="num">{fmt(cp.wind_mph, 1)}</td>
              <td className="num">{fmt(cp.rain_in, 2)}</td>
              <td className="num">{fmt(cp.snow_in, 2)}</td>
              <td>
                <span className="level">
                  <span className="level-dot" style={{ background: levelColor(cp.level) }} />
                  {levelLabel(cp.level)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
