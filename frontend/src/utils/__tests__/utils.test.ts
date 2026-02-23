import { formatDate, formatDateTime, truncate } from '@/lib/utils';

describe('formatDate', () => {
  it('formats ISO date string to "Mon DD, YYYY" locale string', () => {
    const result = formatDate('2025-01-15T00:00:00Z');
    // Allow for timezone differences — verify it contains year and day number
    expect(result).toMatch(/2025/);
    expect(result).toMatch(/15|14/); // Could shift by timezone in CI
  });

  it('contains the month abbreviation', () => {
    const result = formatDate('2025-06-20T12:00:00Z');
    expect(result).toMatch(/Jun/);
  });
});

describe('formatDateTime', () => {
  it('returns a string containing the year', () => {
    const result = formatDateTime('2025-03-01T09:30:00Z');
    expect(result).toMatch(/2025/);
  });

  it('includes time components (hour and minute)', () => {
    const result = formatDateTime('2025-03-01T09:30:00Z');
    // Locale string format includes colon-separated time
    expect(result).toMatch(/\d{1,2}:\d{2}/);
  });
});

describe('truncate', () => {
  it('returns string unchanged when shorter than maxLength', () => {
    expect(truncate('hello', 10)).toBe('hello');
  });

  it('returns string unchanged when equal to maxLength', () => {
    expect(truncate('hello', 5)).toBe('hello');
  });

  it('truncates string and appends ellipsis when longer than maxLength', () => {
    expect(truncate('hello world', 5)).toBe('hello...');
  });

  it('handles empty string', () => {
    expect(truncate('', 5)).toBe('');
  });
});
