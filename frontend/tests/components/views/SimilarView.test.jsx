import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SimilarView from '@/components/views/SimilarView';

const CARD = (id, title) => ({
  id,
  title,
  cover_image_url: null,
  genres: ['Action'],
  similarity_score: 0.5
});

function mockApi() {
  const fetchMock = vi.fn((url) => {
    if (/\/similar\/pages/.test(url)) {
      const page = Number(new URL(url, 'http://x').searchParams.get('page'));
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve(
            page === 1
              ? { results: [CARD(1, 'Gachiakuta'), CARD(2, 'Kagurabachi')], has_more: true }
              : { results: [CARD(3, 'Gosu')], has_more: false }
          )
      });
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ id: 7, title_english: 'Berserk', title_romaji: 'Berserk' })
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('SimilarView (/similar/{id})', () => {
  it('names the source title and lists the first page', async () => {
    mockApi();

    render(
      <SimilarView
        mangaId={7}
        onBack={vi.fn()}
        onCardClick={vi.fn()}
        bookmarks={[]}
        onToggleBookmark={vi.fn()}
        requestLimit={12}
      />
    );

    expect(await screen.findByText('You Might Also Like')).toBeTruthy();
    expect(await screen.findByText('Titles similar to Berserk')).toBeTruthy();
    expect((await screen.findAllByText('Gachiakuta')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Kagurabachi').length).toBeGreaterThan(0);
  });

  it('loads the next page from the one Load More button and hides it at the end', async () => {
    const fetchMock = mockApi();

    render(
      <SimilarView
        mangaId={7}
        onBack={vi.fn()}
        onCardClick={vi.fn()}
        bookmarks={[]}
        onToggleBookmark={vi.fn()}
        requestLimit={12}
      />
    );

    const button = await screen.findByRole('button', { name: /Load More/i });
    fireEvent.click(button);

    expect((await screen.findAllByText('Gosu')).length).toBeGreaterThan(0);
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Load More/i })).toBeNull()
    );
    expect(fetchMock.mock.calls.filter(([url]) => /similar\/pages/.test(url))).toHaveLength(2);
  });

  it('opens a card in the detail modal and goes back from the header', async () => {
    mockApi();
    const onCardClick = vi.fn();
    const onBack = vi.fn();

    render(
      <SimilarView
        mangaId={7}
        onBack={onBack}
        onCardClick={onCardClick}
        bookmarks={[]}
        onToggleBookmark={vi.fn()}
        requestLimit={12}
      />
    );

    fireEvent.click((await screen.findAllByRole('heading', { name: 'Gachiakuta' }))[0]);
    expect(onCardClick).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));

    fireEvent.click(screen.getByRole('button', { name: /Back to results/i }));
    expect(onBack).toHaveBeenCalled();
  });
});
