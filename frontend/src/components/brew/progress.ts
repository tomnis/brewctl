/**
 * Terminal-style progress bar.
 *
 * Callers pass weights *net of the vessel*: scale readings and targets on the wire
 * are gross, and comparing gross weight to a gross target makes an empty vessel read
 * as partly brewed.
 */
export function formatProgressBar(current: number, target: number): string {
  // A vessel at or above the target makes the net denominator zero or negative;
  // 0/0 is NaN, which survives the clamp below and renders as "NaN%".
  if (!(target > 0)) {
    return `[${"░".repeat(20)}] --%`;
  }
  const percent = Math.min(100, Math.max(0, (current / target) * 100));
  const filled = Math.round(percent / 5); // 20 chars = 5% each
  const empty = 20 - filled;
  const bar = "█".repeat(filled) + "░".repeat(empty);
  return `[${bar}] ${percent.toFixed(0)}%`;
}
