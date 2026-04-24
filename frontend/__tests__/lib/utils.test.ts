import { formatDate, formatFullDate, timeAgo } from '../../src/lib/utils';

describe('formatDate', () => {
  it('handles naive timestamps as UTC', () => {
    expect(formatDate('2026-04-23T00:00:00')).toBe('Apr 23, 2026');
  });

  it('handles Z-suffixed timestamps', () => {
    expect(formatDate('2026-04-23T00:00:00Z')).toBe('Apr 23, 2026');
  });

  it('handles negative TZ offsets without producing NaN', () => {
    // 2026-04-23T12:00:00-05:00 === 2026-04-23T17:00:00Z
    expect(formatDate('2026-04-23T12:00:00-05:00')).toBe('Apr 23, 2026');
  });

  it('handles positive TZ offsets', () => {
    // 2026-04-23T12:00:00+09:00 === 2026-04-23T03:00:00Z
    expect(formatDate('2026-04-23T12:00:00+09:00')).toBe('Apr 23, 2026');
  });
});

describe('formatFullDate', () => {
  it('renders a negative-offset timestamp in UTC without NaN', () => {
    const out = formatFullDate('2026-04-23T12:00:00-05:00');
    expect(out).toContain('UTC');
    expect(out).not.toContain('NaN');
  });
});

describe('timeAgo', () => {
  it('returns a non-NaN string for a negative-offset timestamp', () => {
    // Build a past instant, then express it with an explicit negative offset.
    const pastMs = Date.now() - 5 * 60 * 1000;
    const d = new Date(pastMs);
    // Shift wall-clock by -5h so the "-05:00" suffix describes the same instant.
    const shifted = new Date(pastMs - 5 * 60 * 60 * 1000);
    const iso = shifted.toISOString().replace(/Z$/, '-05:00');
    // Sanity check: Date parses it back to the original instant.
    expect(new Date(iso).getTime()).toBe(d.getTime());
    const out = timeAgo(iso);
    expect(out).not.toMatch(/NaN/);
    expect(typeof out).toBe('string');
  });
});
