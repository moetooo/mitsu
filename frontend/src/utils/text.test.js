import { describe, it, expect } from 'vitest';
import { cleanSynopsis, decodeHtmlEntities } from './text';

// FE-28: the same synopsis was cleaned differently in three places, and only two
// entities were patched by hand, so `&amp;` and `&nbsp;` reached the screen.
describe('decodeHtmlEntities', () => {
  it('decodes named and numeric entities', () => {
    expect(decodeHtmlEntities('Tom &amp; Jerry')).toBe('Tom & Jerry');
    expect(decodeHtmlEntities('it&#39;s')).toBe("it's");
    expect(decodeHtmlEntities('it&apos;s')).toBe("it's");
    expect(decodeHtmlEntities('&quot;quoted&quot;')).toBe('"quoted"');
    expect(decodeHtmlEntities('a&nbsp;b')).toBe('a b');
    expect(decodeHtmlEntities('&#x27;hex&#x27;')).toBe("'hex'");
  });

  it('leaves unknown entities and plain text alone', () => {
    expect(decodeHtmlEntities('&notarealentity;')).toBe('&notarealentity;');
    expect(decodeHtmlEntities('plain text')).toBe('plain text');
    expect(decodeHtmlEntities(null)).toBe(null);
  });

  it('does not decode twice', () => {
    expect(decodeHtmlEntities('&amp;lt;')).toBe('&lt;');
  });
});

describe('cleanSynopsis', () => {
  it('strips tags, decodes entities and collapses the whitespace they leave', () => {
    expect(cleanSynopsis('<p>One</p><br><i>Two</i>  &amp; three')).toBe('One Two & three');
  });

  it('returns the fallback for empty, missing and non-string input', () => {
    expect(cleanSynopsis('')).toBe('No synopsis description available for this title.');
    expect(cleanSynopsis('   ')).toBe('No synopsis description available for this title.');
    expect(cleanSynopsis(null)).toBe('No synopsis description available for this title.');
    expect(cleanSynopsis(undefined, 'nothing')).toBe('nothing');
    expect(cleanSynopsis(42, 'nothing')).toBe('42');
  });

  it('treats a decoded angle bracket as text, not as a tag', () => {
    expect(cleanSynopsis('a &lt;b&gt; c')).toBe('a <b> c');
  });
});