/** Small user preferences kept between visits. Storage can be unavailable (private mode, blocked cookies). */
export function readPref<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = window.localStorage.getItem(`trw.${key}`);
    return value && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
  } catch {
    return fallback;
  }
}

export function writePref(key: string, value: string): void {
  try {
    window.localStorage.setItem(`trw.${key}`, value);
  } catch {
    /* preferences are a convenience only */
  }
}
