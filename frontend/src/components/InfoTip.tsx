import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

interface Props {
  /** What the tip explains, used for the button's accessible name. */
  topic: string;
  children: ReactNode;
  /** Bubble above or below the button. It spans the nearest positioned ancestor's width. */
  placement?: 'top' | 'bottom';
}

/**
 * A small help button. The explanation shows on hover or keyboard focus, and a tap pins it open on touch
 * screens. The text is always in the DOM so screen readers get it as the button's description.
 */
export function InfoTip({ topic, children, placement = 'bottom' }: Props) {
  const id = useId();
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const open = hover || pinned;

  // A pinned tip closes on the next tap or click anywhere else.
  useEffect(() => {
    if (!pinned) return;
    const close = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setPinned(false);
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [pinned]);

  return (
    <span
      ref={rootRef}
      className="infotip"
      onPointerEnter={(e) => e.pointerType === 'mouse' && setHover(true)}
      onPointerLeave={(e) => e.pointerType === 'mouse' && setHover(false)}
    >
      <button
        type="button"
        className={`infotip-button${open ? ' is-open' : ''}`}
        aria-label={`About ${topic}`}
        aria-describedby={id}
        aria-expanded={open}
        onClick={() => setPinned((p) => !p)}
        onFocus={() => setHover(true)}
        onBlur={() => {
          setHover(false);
          setPinned(false);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && open) {
            e.stopPropagation();
            setHover(false);
            setPinned(false);
          }
        }}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="8" cy="8" r="6.75" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M8 7.2v4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="8" cy="4.9" r="0.95" fill="currentColor" />
        </svg>
      </button>
      <span id={id} role="tooltip" className={`infotip-bubble infotip-${placement}`} hidden={!open}>
        {children}
      </span>
    </span>
  );
}
