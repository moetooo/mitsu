import { describe, it, expect } from 'vitest';
import { toBookmarkRecord, toggleBookmark, toStoredBookmarks, MAX_BOOKMARKS } from './bookmarks';

// FE-18: saved titles were the whole API result, appended without a cap, so the
// stored blob grew past the localStorage quota and the write started failing.

const fullResult = {
  id: 7,
  title: 'Berserk',
  cover_image_url: 'https://example.test/cover.jpg',
  average_score: 9.4,
  start_year: 1989,
  status: 'FINISHED',
  genres: ['Action', 'Drama'],
  synopsis: 'A long description.',
  // fields no display surface reads; these are what made the blob large
  embedding: [0.1, 0.2, 0.3],
  retrieval_debug: { score: 0.42, candidates: 200 },
  pipeline_run_id: 'abc'
};

describe('toBookmarkRecord', () => {
  it('keeps what the card and the modal read', () => {
    const record = toBookmarkRecord(fullResult);
    expect(record.id).toBe(7);
    expect(record.title).toBe('Berserk');
    expect(record.cover_image_url).toBe('https://example.test/cover.jpg');
    expect(record.average_score).toBe(9.4);
    expect(record.synopsis).toBe('A long description.');
  });

  it('drops fields no display surface reads', () => {
    const record = toBookmarkRecord(fullResult);
    expect(record).not.toHaveProperty('embedding');
    expect(record).not.toHaveProperty('retrieval_debug');
    expect(record).not.toHaveProperty('pipeline_run_id');
  });

  it('refuses a record without an id', () => {
    expect(toBookmarkRecord({ title: 'Nameless' })).toBeNull();
    expect(toBookmarkRecord(null)).toBeNull();
  });
});

describe('toggleBookmark', () => {
  it('adds, then removes on the second call', () => {
    const once = toggleBookmark([], fullResult);
    expect(once).toHaveLength(1);
    expect(once[0].id).toBe(7);

    const twice = toggleBookmark(once, fullResult);
    expect(twice).toHaveLength(0);
  });

  it('keeps the list bounded, dropping the oldest entries', () => {
    let list = [];
    for (let id = 1; id <= MAX_BOOKMARKS + 5; id += 1) {
      list = toggleBookmark(list, { id, title: `Title ${id}` });
    }
    expect(list).toHaveLength(MAX_BOOKMARKS);
    // The first five were pushed out, not silently mixed in.
    expect(list[0].id).toBe(6);
    expect(list[list.length - 1].id).toBe(MAX_BOOKMARKS + 5);
  });

  it('ignores a title without an id', () => {
    expect(toggleBookmark([], { title: 'Nameless' })).toEqual([]);
  });
});

describe('toStoredBookmarks', () => {
  it('projects and caps what is written to disk', () => {
    const loaded = Array.from({ length: MAX_BOOKMARKS + 20 }, (_, i) => ({
      ...fullResult,
      id: i + 1
    }));

    const stored = toStoredBookmarks(loaded);

    expect(stored).toHaveLength(MAX_BOOKMARKS);
    expect(stored[0]).not.toHaveProperty('embedding');
    // The newest survive, matching what the user last saved.
    expect(stored[stored.length - 1].id).toBe(MAX_BOOKMARKS + 20);
  });

  it('survives junk input', () => {
    expect(toStoredBookmarks(null)).toEqual([]);
    expect(toStoredBookmarks([null, {}, { id: 3 }])).toEqual([{ id: 3 }]);
  });
});
