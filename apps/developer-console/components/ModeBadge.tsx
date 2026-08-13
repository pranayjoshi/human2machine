export function ModeBadge({ mode }: { mode?: string | null }) {
  const physical = Boolean(mode && /physical/i.test(mode) && !/simulator/i.test(mode));
  if (physical) {
    return (
      <div className="mode-banner physical" role="status">
        Physical robot mode — hardware can move
      </div>
    );
  }
  return (
    <div className="mode-banner simulator" role="status">
      Simulator mode — no physical robot armed
    </div>
  );
}
