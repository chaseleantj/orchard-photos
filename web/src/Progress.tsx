/** A thin bar for work that takes a while. Omit `value` when the amount done is unknown. */
export function Progress({ value, label }: { value?: number | null; label: string }) {
  const known = typeof value === 'number';
  return <div className="progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? Math.round(value * 100) : undefined} data-indeterminate={known ? undefined : ''}>
    <span style={known ? { width: `${Math.max(0, Math.min(1, value)) * 100}%` } : undefined} />
  </div>;
}
