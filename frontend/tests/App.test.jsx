import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within, act } from '@testing-library/react';
import App from '@/App';

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, '', '/');
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })));
});

const TRENDING_ROWS = [
  { id: 1, title: 'Chainsaw Man', cover_image_url: null, average_score: 84, start_year: 2018, genres: [], tags: [] },
  { id: 2, title: 'Solo Leveling', cover_image_url: null, average_score: 84, start_year: 2018, genres: [], tags: [] }
];

// The rail reads `/manga/trending`; everything else answers like the default stub.
const stubCatalog = (rows = TRENDING_ROWS) =>
  vi.fn(url =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(String(url).includes('/manga/trending') ? rows : [])
    })
  );

describe('Explore opens on the Trending rail', () => {
  it('shows the rail on arrival, with no pill rows and no catalogue request', async () => {
    vi.stubGlobal('fetch', stubCatalog());
    render(<App />);
    await act(async () => {});

    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(nav).getByRole('button', { name: /explore/i })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).queryByRole('button', { name: /trending/i })).toBeNull();

    // The section: a word, a hairline, a format toggle, a rail. No icon, no
    // hand-over tile. Scoped to the region because the hero slides the same rows.
    const section = screen.getByRole('region', { name: 'Trending' });
    expect(within(section).getByRole('heading', { name: 'Trending' })).toBeTruthy();
    expect(within(section).getAllByText('Chainsaw Man').length).toBeGreaterThan(0);

    const toggle = within(section).getByRole('group', { name: 'Trending format' });
    expect(within(toggle).getAllByRole('button').map(node => node.textContent)).toEqual([
      'Manga',
      'Manhwa',
      'Manhua'
    ]);
    expect(within(toggle).getByRole('button', { name: 'Manga' })).toHaveAttribute('aria-pressed', 'true');

    // No way to leave the page from the section: the rail is the whole surface.
    expect(within(section).queryByRole('button', { name: /see all trending titles/i })).toBeNull();
    expect(screen.queryByRole('group', { name: 'Browse format' })).toBeNull();
    expect(screen.queryByRole('group', { name: 'Browse genre' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'All Formats' })).toBeNull();

    // Arrival no longer browses the catalogue: the grid belongs to a query.
    const recommends = globalThis.fetch.mock.calls.filter(([url]) => String(url).endsWith('/recommend'));
    expect(recommends).toHaveLength(0);
    expect(screen.queryByText(/Top titles/i)).toBeNull();
  });

  it('hides the rail once a search lands, and brings it back when the set is cleared', async () => {
    vi.stubGlobal('fetch', stubCatalog());
    render(<App />);
    await act(async () => {});

    const input = screen.getByRole('combobox', { name: /search manga/i });
    fireEvent.change(input, { target: { value: 'dark fantasy' } });
    await act(async () => {
      fireEvent.submit(input.closest('form'));
    });

    expect(screen.queryByRole('heading', { name: 'Trending' })).toBeNull();

    await act(async () => {
      fireEvent.change(input, { target: { value: '' } });
      fireEvent.submit(input.closest('form'));
    });

    expect(screen.getByRole('heading', { name: 'Trending' })).toBeTruthy();
    expect(window.location.search).toBe('');
  });

  it('switches the rail format in place, without navigating', async () => {
    const fetchMock = vi.fn(url =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve(
            String(url).includes('format_type=manhwa')
              ? [{ ...TRENDING_ROWS[0], id: 2, title: 'Solo Leveling' }]
              : TRENDING_ROWS
          )
      })
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    await act(async () => {});

    const toggle = screen.getByRole('group', { name: 'Trending format' });
    fireEvent.click(within(toggle).getByRole('button', { name: 'Manhwa' }));
    await act(async () => {});

    // One request per selection, and the URL does not move at all.
    const requests = fetchMock.mock.calls.map(([url]) => String(url)).filter(url => url.includes('/manga/trending'));
    expect(requests).toHaveLength(2);
    expect(requests[1]).toContain('format_type=manhwa');
    expect(requests[1]).toContain('limit=10');
    expect(window.location.pathname).toBe('/');
    expect(window.location.search).toBe('');
    expect(within(toggle).getByRole('button', { name: 'Manhwa' })).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('there is no trending route any more', () => {
  it('reads a /trending link as Explore and shows the rail', async () => {
    vi.stubGlobal('fetch', stubCatalog());
    window.history.replaceState({}, '', '/trending');
    render(<App />);
    await act(async () => {});

    expect(await screen.findByRole('region', { name: 'Trending' })).toBeTruthy();
    // The page is gone: no heading of its own, only the rail's section heading.
    expect(screen.queryByText(/← Back to explore/i)).toBeNull();
    expect(screen.getByRole('group', { name: 'Trending format' })).toBeTruthy();
  });
});

describe('A result set is an answer, not a ranking', () => {
  const RESULTS = [
    {
      id: 11,
      title: 'Berserk',
      cover_image_url: null,
      average_score: 90,
      start_year: 1989,
      genres: [],
      tags: [],
      similarity_score: 0.87
    }
  ];

  const stubResults = () =>
    vi.fn(url =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve(
            String(url).includes('/manga/trending')
              ? TRENDING_ROWS
              : { results: RESULTS, has_next: false }
          )
      })
    );

  const applyStatusFilter = async () => {
    fireEvent.click(screen.getByRole('button', { name: /filters/i }));
    expect(
      await screen.findByRole('heading', { name: /advanced search filters/i }, { timeout: 5000 })
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'FINISHED' }));
    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));
    await act(async () => {});
  };

  it('never numbers its rows, even for a filter-only browse', async () => {
    vi.stubGlobal('fetch', stubResults());
    render(<App />);
    await act(async () => {});

    await applyStatusFilter();

    // The count says Results, and there is no "#1" anywhere: ranking is the
    // /trending page's job, and a browse is not the trending list.
    expect(screen.getByText(/Results \(1\)/)).toBeTruthy();
    expect(screen.queryByText('#1')).toBeNull();
    expect(screen.queryByText(/Top titles/i)).toBeNull();
    // The rail steps aside for a result set.
    expect(screen.queryByRole('region', { name: 'Trending' })).toBeNull();
  });

  it('shows a match percentage only when there is a query to match', async () => {
    vi.stubGlobal('fetch', stubResults());
    render(<App />);
    await act(async () => {});

    // A filter-only browse has no query, so a similarity score would be noise.
    await applyStatusFilter();
    expect(screen.queryByText('87%')).toBeNull();

    const input = screen.getByRole('combobox', { name: /search manga/i });
    fireEvent.change(input, { target: { value: 'berserk' } });
    await act(async () => {
      fireEvent.submit(input.closest('form'));
    });

    expect(await screen.findByText('87%')).toBeTruthy();
  });
});

describe('Explore search applies the drawer filters (B-01)', () => {
  it('sends the active filters with a typed search, like retry, tag click and load more already do', async () => {
    render(<App />);
    const fetchMock = globalThis.fetch;

    // The drawer is a lazy chunk, so it mounts after its module resolves.
    fireEvent.click(screen.getByRole('button', { name: /filters/i }));
    // The drawer is a lazy chunk: in a cold worker the module graph can take longer
    // than the default 1s to resolve, which is a harness timing issue, not the drawer.
    expect(
      await screen.findByRole('heading', { name: /advanced search filters/i }, { timeout: 5000 })
    ).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'FINISHED' }));
    // Filters are staged now: the pill edits the drawer's draft, and Apply is the
    // one commit point (and it closes the drawer).
    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));

    const input = screen.getByRole('combobox', { name: /search manga/i });
    fireEvent.change(input, { target: { value: 'dark fantasy' } });
    await act(async () => {
      fireEvent.submit(input.closest('form'));
    });

    // Apply with an empty box is now a browse, so the typed submit is the last
    // `/recommend` call rather than the first.
    const recommends = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/recommend'));
    expect(recommends.length).toBeGreaterThan(0);
    const body = JSON.parse(recommends[recommends.length - 1][1].body);
    expect(body.query).toBe('dark fantasy');
    // The drawer's status pill was active; dropping it here made page 1
    // unfiltered while Load More sent the filters for page 2.
    expect(body.filters.status).toEqual(['FINISHED']);
  });
});

describe('Surprise drawer taxonomy (B-04)', () => {
  // A served taxonomy containing a group the built-in fallback does not have, so
  // the two are distinguishable: the fallback is 3 fixed groups, the server up to 6.
  const SERVED = {
    version: 42,
    categories: [
      { id: 'mood', label: 'Moods', options: [{ value: 'heartwarming' }] },
      { id: 'setting', label: 'Tropes', options: [{ value: 'space opera' }] }
    ],
    formats: [{ value: 'MANGA', filterable: true }]
  };
  const ROW = {
    id: 9001,
    title: 'Surprise Title',
    cover_image_url: null,
    average_score: 8.1,
    start_year: 2021,
    genres: [],
    tags: [],
    status: 'FINISHED',
    format_type: 'MANGA',
    synopsis: ''
  };

  it('renders the served groups in Surprise Me instead of the frozen fallback', async () => {
    window.history.replaceState({}, '', '/surprise');
    vi.stubGlobal('fetch', vi.fn((url) => {
      const target = String(url);
      const body = target.endsWith('/vocabulary') ? SERVED
        : target.endsWith('/roulette/batch') ? []
        : target.endsWith('/roulette') ? ROW
        : [];
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    }));

    render(<App />);

    // The floating button only exists once a title is queued, so this walks the
    // same path a user takes to reach the drawer from the Surprise Me tab.
    fireEvent.click(await screen.findByRole('button', { name: 'Discovery Filters' }, { timeout: 4000 }));

    // The served group gets its own category tab, which only the server list has.
    expect(await screen.findByRole('button', { name: /^Moods/ }, { timeout: 4000 })).toBeTruthy();
    // A fallback-only group: proof the drawer switched taxonomy rather than
    // rendering both lists side by side.
    expect(screen.queryByText('Demographics')).toBeNull();
  });
});

describe('App tab switching (FE-24)', () => {
  it('does not remount the tab container when the tab changes', async () => {
    const { container } = render(<App />);
    const before = container.querySelector('.animate-tab-fade-in');
    expect(before).toBeTruthy();

    const nav = screen.getByRole('navigation', { name: 'Primary' });
    fireEvent.click(within(nav).getByRole('button', { name: /saved/i }));
    await act(async () => {});
    fireEvent.click(within(nav).getByRole('button', { name: /explore/i }));
    await act(async () => {});

    // Same DOM node: `key={activeTab}` used to rebuild it here, which reset any
    // state living inside a tab (the discovery queue used to be one of those).
    expect(container.querySelector('.animate-tab-fade-in')).toBe(before);
  });
});

describe('Applying drawer filters (staged Apply)', () => {
  it('re-runs page 1 of the current query so the grid cannot show the old predicate', async () => {
    render(<App />);
    const fetchMock = globalThis.fetch;

    const input = screen.getByRole('combobox', { name: /search manga/i });
    fireEvent.change(input, { target: { value: 'ghost stories' } });
    await act(async () => {
      fireEvent.submit(input.closest('form'));
    });

    const firstRecommend = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/recommend'));
    expect(firstRecommend).toHaveLength(1);
    expect(JSON.parse(firstRecommend[0][1].body).filters.status).toEqual([]);

    fireEvent.click(screen.getByRole('button', { name: /filters/i }));
    // The drawer is a lazy chunk: in a cold worker the module graph can take longer
    // than the default 1s to resolve, which is a harness timing issue, not the drawer.
    expect(
      await screen.findByRole('heading', { name: /advanced search filters/i }, { timeout: 5000 })
    ).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'FINISHED' }));
    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));
    await act(async () => {});

    const recommends = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/recommend'));
    expect(recommends).toHaveLength(2);
    const applied = JSON.parse(recommends[recommends.length - 1][1].body);
    expect(applied.query).toBe('ghost stories');
    expect(applied.page).toBe(1);
    expect(applied.filters.status).toEqual(['FINISHED']);

    // Apply is also the close button, so the results are visible immediately.
    expect(screen.queryByRole('heading', { name: /advanced search filters/i })).toBeNull();
  });

  it('browses the catalogue when only a filter is applied', async () => {
    render(<App />);
    const fetchMock = globalThis.fetch;

    fireEvent.click(screen.getByRole('button', { name: /filters/i }));
    // The drawer is a lazy chunk: in a cold worker the module graph can take longer
    // than the default 1s to resolve, which is a harness timing issue, not the drawer.
    expect(
      await screen.findByRole('heading', { name: /advanced search filters/i }, { timeout: 5000 })
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'FINISHED' }));
    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));
    await act(async () => {});

    const recommends = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/recommend'));
    expect(recommends).toHaveLength(1);
    const body = JSON.parse(recommends[0][1].body);
    expect(body.query).toBe('');
    expect(body.filters.status).toEqual(['FINISHED']);
    expect(body.page).toBe(1);
    expect(screen.getByRole('button', { name: /filters/i }).textContent).toContain('1');
  });
});

describe('Apply works without a prior submit (reported bug)', () => {
  const openDrawer = async () => {
    fireEvent.click(screen.getByRole('button', { name: /filters/i }));
    expect(
      await screen.findByRole('heading', { name: /advanced search filters/i }, { timeout: 5000 })
    ).toBeTruthy();
  };

  it('searches immediately when a query is typed but never submitted', async () => {
    render(<App />);
    const fetchMock = globalThis.fetch;

    const input = screen.getByRole('combobox', { name: /search manga/i });
    fireEvent.change(input, { target: { value: 'quiet romance' } });

    await openDrawer();
    fireEvent.click(screen.getByRole('button', { name: 'FINISHED' }));
    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));
    await act(async () => {});

    const recommends = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/recommend'));
    expect(recommends).toHaveLength(1);
    const body = JSON.parse(recommends[0][1].body);
    expect(body.query).toBe('quiet romance');
    expect(body.filters.status).toEqual(['FINISHED']);
  });

  it('applies a filter with an empty search box instead of staging it', async () => {
    render(<App />);
    const fetchMock = globalThis.fetch;

    await openDrawer();
    fireEvent.click(screen.getByRole('button', { name: 'FINISHED' }));
    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));
    await act(async () => {});

    const recommends = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/recommend'));
    expect(recommends).toHaveLength(1);
    const body = JSON.parse(recommends[0][1].body);
    expect(body.query).toBe('');
    expect(body.filters.status).toEqual(['FINISHED']);
  });
});

describe('Explore state lives in the URL (FE-34)', () => {
  const submit = async (value) => {
    const input = screen.getByRole('combobox', { name: /search manga/i });
    fireEvent.change(input, { target: { value } });
    await act(async () => {
      fireEvent.submit(input.closest('form'));
    });
  };

  const recommendCalls = () =>
    globalThis.fetch.mock.calls.filter(([url]) => String(url).endsWith('/recommend'));

  it('writes the submitted query into the address bar', async () => {
    render(<App />);
    await submit('ghost stories');

    expect(window.location.search).toContain('q=ghost+stories');
    // Defaults stay out of the URL: no sort, no page.
    expect(window.location.search).not.toContain('sort=');
    expect(window.location.search).not.toContain('page=');
  });

  it('writes filters applied with an empty box', async () => {
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: /filters/i }));
    expect(
      await screen.findByRole('heading', { name: /advanced search filters/i }, { timeout: 5000 })
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'FINISHED' }));
    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));
    await act(async () => {});

    expect(window.location.search).toContain('status=FINISHED');
    const body = JSON.parse(recommendCalls().at(-1)[1].body);
    expect(body.query).toBe('');
  });

  it('re-requests page 1 when the sort changes and writes it to the URL', async () => {
    const rows = Array.from({ length: 4 }, (_, index) => ({
      id: index + 1,
      title: `Title ${index + 1}`,
      cover_image_url: null,
      average_score: 8,
      start_year: 2010,
      genres: [],
      tags: []
    }));
    globalThis.fetch.mockImplementation(() =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ results: rows }) })
    );

    render(<App />);
    await submit('action');

    const before = recommendCalls().length;
    fireEvent.click(screen.getByRole('button', { name: 'Popularity' }));
    await act(async () => {});

    expect(window.location.search).toContain('sort=popularity');
    const calls = recommendCalls();
    expect(calls.length).toBe(before + 1);
    const body = JSON.parse(calls[calls.length - 1][1].body);
    expect(body.sort).toBe('popularity');
    expect(body.page).toBe(1);
  });

  it('resets query, filters, sort and page from the Mitsu logo', async () => {
    window.history.replaceState({}, '', '/?q=ghost&status=FINISHED&sort=popularity&page=2');
    render(<App />);
    await act(async () => {});

    fireEvent.click(screen.getByRole('button', { name: 'Mitsu home' }));
    await act(async () => {});

    expect(window.location.pathname).toBe('/');
    expect(window.location.search).toBe('');
    expect(screen.getByRole('combobox', { name: /search manga/i }).value).toBe('');
  });

  it('does not render the backend title suggestion as "Did you mean"', async () => {
    globalThis.fetch.mockImplementation(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            results: [],
            title_suggestion: { id: 1, title: 'Berserk' }
          })
      })
    );

    render(<App />);
    await submit('bersek');
    await act(async () => {});

    expect(screen.queryByText(/did you mean/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /did you mean/i })).toBeNull();
  });

  it('restores a bookmarked URL on first render', async () => {
    window.history.replaceState({}, '', '/?q=deep+link&sort=relevance&page=1');
    render(<App />);
    await act(async () => {});

    const body = JSON.parse(recommendCalls()[0][1].body);
    expect(body.query).toBe('deep link');
    expect(body.sort).toBe('relevance');
    expect(body.page).toBe(1);
    expect(screen.getByRole('combobox', { name: /search manga/i })).toHaveValue('deep link');
  });

  it('replays the URL state on Back/Forward', async () => {
    render(<App />);
    await submit('first query');

    const before = recommendCalls().length;
    act(() => {
      window.history.replaceState({}, '', '/?q=previous+query');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    await act(async () => {});

    const calls = recommendCalls();
    expect(calls.length).toBeGreaterThan(before);
    const body = JSON.parse(calls[calls.length - 1][1].body);
    expect(body.query).toBe('previous query');
    expect(screen.getByRole('combobox', { name: /search manga/i })).toHaveValue('previous query');
  });

  it('puts Load More in the URL as a replacement page, not a new intent', async () => {
    const rows = Array.from({ length: 12 }, (_, index) => ({
      id: index + 1,
      title: `Title ${index + 1}`,
      cover_image_url: null,
      average_score: 8,
      start_year: 2010,
      genres: [],
      tags: []
    }));
    globalThis.fetch.mockImplementation(() =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ results: rows }) })
    );

    render(<App />);
    await submit('action');

    expect(screen.getAllByRole('button', { name: 'Load More' })).toHaveLength(1);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Load More' }));
    });

    const body = JSON.parse(recommendCalls().at(-1)[1].body);
    expect(body.page).toBe(2);
    expect(window.location.search).toContain('page=2');
  });

  it('turns an emptied box back into the arrival state instead of a stale result set', async () => {
    render(<App />);
    await submit('cats');
    const before = recommendCalls().length;

    const input = screen.getByRole('combobox', { name: /search manga/i });
    await act(async () => {
      fireEvent.change(input, { target: { value: '' } });
      fireEvent.submit(input.closest('form'));
    });

    // No criteria left is not a request any more: the rows are dropped and the
    // URL says "nothing searched", so the Trending rail is the page again.
    expect(recommendCalls()).toHaveLength(before);
    expect(window.location.search).not.toContain('q=');
    expect(screen.queryByText(/No titles found/i)).toBeNull();
  });

  it('clamps a deep-linked page past the end back to the last page with rows', async () => {
    const pageRows = Array.from({ length: 12 }, (_, index) => ({
      id: index + 1,
      title: `Title ${index + 1}`,
      cover_image_url: null,
      average_score: 8,
      start_year: 2010,
      genres: [],
      tags: []
    }));
    globalThis.fetch.mockImplementation((url, opts) => {
      const page = opts && opts.body ? JSON.parse(opts.body).page : 1;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ results: opts && opts.body && page <= 2 ? pageRows : [] })
      });
    });

    window.history.replaceState({}, '', '/?q=deep&page=9');
    render(<App />);
    await act(async () => {});

    // Two pages exist; page 3 comes back empty, so the URL says page 2.
    expect(window.location.search).toContain('page=2');
    expect(window.location.search).not.toContain('page=9');
  });
});
