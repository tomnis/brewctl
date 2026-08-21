import { describe, it, expect } from 'vitest';
import { formatProgressBar } from './progress';

const percent = (bar: string) => bar.slice(bar.indexOf('] ') + 2);

describe('formatProgressBar', () => {
  it('reads 0% for an empty vessel on the scale', () => {
    // 229 g vessel, 1337 g gross target: the old gross math read 17% here.
    expect(percent(formatProgressBar(229 - 229, 1337 - 229))).toBe('0%');
  });

  it('reads 50% at half the coffee target', () => {
    expect(percent(formatProgressBar(783 - 229, 1337 - 229))).toBe('50%');
  });

  it('reads 100% at the target', () => {
    expect(percent(formatProgressBar(1337 - 229, 1337 - 229))).toBe('100%');
  });

  it('clamps overshoot to 100%', () => {
    expect(percent(formatProgressBar(2000, 1108))).toBe('100%');
  });

  it('clamps a negative reading to 0%', () => {
    expect(percent(formatProgressBar(-50, 1108))).toBe('0%');
  });

  it('renders --% rather than NaN% when the vessel meets or exceeds the target', () => {
    expect(percent(formatProgressBar(0, 0))).toBe('--%');
    expect(percent(formatProgressBar(10, -5))).toBe('--%');
  });

  it('keeps the bar 20 cells wide', () => {
    const bar = formatProgressBar(554, 1108);
    expect(bar.slice(1, bar.indexOf(']')).length).toBe(20);
  });
});
