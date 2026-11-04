import { useEffect, useId, useRef, useState } from 'react';
import { api } from '../lib/api';
import type { Place } from '../types';

interface Props {
  label: string;
  value: Place | null;
  onChange: (place: Place | null) => void;
  placeholder?: string;
  error?: string;
  /** The map is waiting for a click to set this field. */
  picking: boolean;
  onPickToggle: () => void;
  onFocusField: () => void;
}

const MIN_CHARS = 3;
const DEBOUNCE_MS = 220;

export function PlaceInput({ label, value, onChange, placeholder, error, picking, onPickToggle, onFocusField }: Props) {
  const id = useId();
  const listId = `${id}-list`;
  const [text, setText] = useState(value?.label ?? '');
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState<'idle' | 'loading' | 'empty' | 'error'>('idle');
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number>();
  const clearedByTyping = useRef(false);
  const blurTimer = useRef<number>();

  // Reflect selections made outside the input (swap, example trip), but keep
  // the text when the selection was cleared because the user started typing.
  useEffect(() => {
    if (clearedByTyping.current) {
      clearedByTyping.current = false;
      return;
    }
    setText(value?.label ?? '');
  }, [value]);

  useEffect(
    () => () => {
      window.clearTimeout(timerRef.current);
      window.clearTimeout(blurTimer.current);
      abortRef.current?.abort();
    },
    [],
  );

  function search(query: string) {
    window.clearTimeout(timerRef.current);
    abortRef.current?.abort();
    if (query.trim().length < MIN_CHARS) {
      setResults([]);
      setStatus('idle');
      return;
    }
    timerRef.current = window.setTimeout(async () => {
      const controller = new AbortController();
      abortRef.current = controller;
      setStatus('loading');
      try {
        const places = await api.places(query.trim(), controller.signal);
        setResults(places);
        setActive(places.length ? 0 : -1);
        setStatus(places.length ? 'idle' : 'empty');
      } catch (err) {
        if ((err as Error).name !== 'AbortError') setStatus('error');
      }
    }, DEBOUNCE_MS);
  }

  function choose(place: Place) {
    window.clearTimeout(blurTimer.current);
    onChange(place);
    setText(place.label);
    setOpen(false);
    setResults([]);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown' && results.length) {
      e.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % results.length);
    } else if (e.key === 'ArrowUp' && results.length) {
      e.preventDefault();
      setActive((i) => (i <= 0 ? results.length - 1 : i - 1));
    } else if (e.key === 'Enter' && open && active >= 0 && results[active]) {
      e.preventDefault();
      choose(results[active]);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  }

  const showList = open && (results.length > 0 || status === 'empty' || status === 'error');

  return (
    <div className="field" data-place-field>
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      <div className="combo">
        <input
          id={id}
          className={`input input-with-pick${error ? ' input-invalid' : ''}${picking ? ' input-picking' : ''}`}
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && active >= 0 ? `${listId}-${active}` : undefined}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder={picking ? 'Click the map, or type a place' : placeholder}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            if (value) {
              clearedByTyping.current = true;
              onChange(null);
            }
            search(e.target.value);
          }}
          onFocus={() => {
            window.clearTimeout(blurTimer.current);
            if (results.length) setOpen(true);
            onFocusField();
          }}
          // Closing is delayed so a tap on a suggestion lands before the list disappears on touch screens.
          onBlur={() => {
            blurTimer.current = window.setTimeout(() => setOpen(false), 150);
          }}
          onKeyDown={onKeyDown}
        />
        {status === 'loading' && <span className="combo-spinner" aria-hidden="true" />}
        <button
          type="button"
          className={`combo-pick${picking ? ' is-active' : ''}`}
          aria-label={`Choose ${label} on the map`}
          aria-pressed={picking}
          title={picking ? 'Click the map to place it. Press Esc to cancel.' : `Choose ${label} on the map`}
          onClick={() => {
            setOpen(false);
            onPickToggle();
          }}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="8" cy="8" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <circle cx="8" cy="8" r="1.4" fill="currentColor" />
            <path
              d="M8 1v2.2M8 12.8V15M1 8h2.2M12.8 8H15"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
        {showList && (
          <ul id={listId} role="listbox" className="combo-list">
            {results.map((place, i) => (
              <li
                key={`${place.label}-${place.lat}-${place.lon}`}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                className={`combo-option${i === active ? ' is-active' : ''}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(place)}
                onMouseEnter={() => setActive(i)}
              >
                <span className="combo-option-label">{place.label}</span>
                {place.detail && <span className="combo-option-detail">{place.detail}</span>}
              </li>
            ))}
            {status === 'empty' && <li className="combo-message">No places match “{text.trim()}”.</li>}
            {status === 'error' && <li className="combo-message">Place search is unavailable. Try again.</li>}
          </ul>
        )}
      </div>
      {error && (
        <p id={`${id}-error`} className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}
