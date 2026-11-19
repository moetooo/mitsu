import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  __resetCoverReports,
  reportBrokenCover,
  setCoverReportingEnabled,
} from '@/utils/coverReports';

describe('reportBrokenCover', () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 202 });
    globalThis.fetch = fetchMock;
    __resetCoverReports();
    setCoverReportingEnabled(true);
  });

  afterEach(() => {
    setCoverReportingEnabled(false);
    vi.restoreAllMocks();
  });

  it('posts the title id and the reason', () => {
    reportBrokenCover(42);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toContain('/covers/42/broken');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ reason: 'all_candidates_failed' });
    expect(options.keepalive).toBe(true);
  });

  it('reports a title only once per session', () => {
    reportBrokenCover(42);
    reportBrokenCover(42);
    reportBrokenCover(42);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('reports different titles separately', () => {
    reportBrokenCover(42);
    reportBrokenCover(43);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('ignores a manga without an id', () => {
    reportBrokenCover(undefined);
    reportBrokenCover(null);
    reportBrokenCover(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('stays silent when the request rejects', async () => {
    fetchMock.mockRejectedValue(new Error('offline'));
    expect(() => reportBrokenCover(7)).not.toThrow();
    await Promise.resolve();
  });

  it('stays silent when fetch itself throws synchronously', () => {
    globalThis.fetch = () => {
      throw new Error('blocked by an extension');
    };
    expect(() => reportBrokenCover(8)).not.toThrow();
  });

  it('does nothing while reporting is disabled', () => {
    setCoverReportingEnabled(false);
    reportBrokenCover(9);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
