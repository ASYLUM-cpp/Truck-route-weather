const timeFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});
const intFmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });

export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m} min`;
  return `${h} h ${String(m).padStart(2, '0')} min`;
}

export function formatMiles(mi: number): string {
  return mi >= 10 || mi === 0 ? `${intFmt.format(mi)} mi` : `${mi.toFixed(1)} mi`;
}

export function formatInt(n: number): string {
  return intFmt.format(n);
}

export function formatTime(iso: string): string {
  return timeFmt.format(new Date(iso));
}

export function formatDateTime(iso: string | Date): string {
  return dateTimeFmt.format(typeof iso === 'string' ? new Date(iso) : iso);
}

export function timeZoneName(): string {
  const part = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' })
    .formatToParts(new Date())
    .find((p) => p.type === 'timeZoneName');
  return part?.value ?? 'local time';
}

/** Value for <input type="datetime-local"> in the browser's time zone. */
export function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

export function nextFullHour(from = new Date()): Date {
  const d = new Date(from);
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return d;
}
