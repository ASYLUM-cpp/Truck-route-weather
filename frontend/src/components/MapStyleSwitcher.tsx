import { useEffect, useId, useRef, useState } from 'react';
import { MAP_STYLES, type MapStyleId } from '../lib/mapStyles';

interface Props {
  value: MapStyleId;
  onChange: (id: MapStyleId) => void;
}

/** Map type button under the zoom controls, opening a short list of basemaps. */
export function MapStyleSwitcher({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [open]);

  return (
    <div
      ref={rootRef}
      className="map-style"
      onKeyDown={(e) => {
        if (e.key === 'Escape' && open) {
          e.stopPropagation();
          setOpen(false);
          rootRef.current?.querySelector<HTMLButtonElement>('.map-style-button')?.focus();
        }
      }}
    >
      <button
        type="button"
        className={`map-style-button${open ? ' is-open' : ''}`}
        aria-label="Map type"
        title="Map type"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((o) => !o)}
      >
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
          <path
            d="M9 2.5 16 6.25 9 10 2 6.25Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
          <path
            d="M2 9.25 9 13l7-3.75M2 12.25 9 16l7-3.75"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {open && (
        <div id={menuId} className="map-style-menu" role="radiogroup" aria-label="Map type">
          {MAP_STYLES.map((s) => (
            <button
              key={s.id}
              type="button"
              role="radio"
              aria-checked={s.id === value}
              className={`map-style-option${s.id === value ? ' is-checked' : ''}`}
              onClick={() => {
                onChange(s.id);
                setOpen(false);
              }}
            >
              <span
                className="map-style-preview"
                aria-hidden="true"
                style={{ background: `linear-gradient(135deg, ${s.preview[0]} 0 55%, ${s.preview[1]} 55% 100%)` }}
              />
              {s.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
