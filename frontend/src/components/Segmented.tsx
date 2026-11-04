interface Option<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
  /** Explains why an option is disabled. */
  hint?: string;
}

interface Props<T extends string> {
  label: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: 'regular' | 'small' | 'inline';
  hideLabel?: boolean;
}

/** A group of mutually exclusive buttons, exposed to assistive tech as a radio group. */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  size = 'regular',
  hideLabel,
}: Props<T>) {
  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const step =
      e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const idx = options.findIndex((o) => o.value === value);
    let next = idx;
    for (let i = 0; i < options.length; i++) {
      next = (next + step + options.length) % options.length;
      if (!options[next].disabled) break;
    }
    onChange(options[next].value);
    const buttons = e.currentTarget.querySelectorAll<HTMLButtonElement>('button');
    buttons[next]?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={`segmented segmented-${size}`}
      onKeyDown={onKeyDown}
      title={hideLabel ? label : undefined}
    >
      {options.map((o) => {
        const checked = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            disabled={o.disabled}
            title={o.disabled ? o.hint : undefined}
            className={`segmented-option${checked ? ' is-checked' : ''}`}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
