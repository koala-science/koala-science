import { formatDistance } from '../lib/distance-fmt';

describe('formatDistance', () => {
  it('returns "cleared" for passer distance 0', () => {
    expect(formatDistance(0)).toBe('cleared');
  });

  it('returns a signed pill for small finite distances', () => {
    expect(formatDistance(0.04)).toBe('+0.04');
    expect(formatDistance(0.3)).toBe('+0.30');
    expect(formatDistance(0.999)).toBe('+1.00');
  });

  it('returns "far" for mid-range distances', () => {
    expect(formatDistance(1.0)).toBe('far');
    expect(formatDistance(1.5)).toBe('far');
  });

  it('returns "very far" at the pinned-to-axis worst case', () => {
    expect(formatDistance(2.0)).toBe('very far');
    expect(formatDistance(3.0)).toBe('very far');
  });

  it('treats negative input as cleared (defensive)', () => {
    expect(formatDistance(-0.5)).toBe('cleared');
  });
});
