// Renders AI answers (paragraphs, bullets, bold, [n] citations), source lists and Search suggestions.

import { externalLink, h } from './dom.js';
import { parseInline, parseRich, safeUrl } from './utils.js';

function renderTokens(tokens, byN) {
  return tokens.map((t) => {
    if (t.type === 'strong') return h('strong', { text: t.value });
    if (t.type === 'cite') {
      const src = byN.get(t.value);
      return src ? h('sup', {}, externalLink(safeUrl(src.uri), `[${t.value}]`, { title: src.title })) : `[${t.value}]`;
    }
    return t.value;
  });
}

/** Inline-only rendering (used for advisory bullets). */
export const renderInline = (text, sources = []) =>
  renderTokens(parseInline(text), new Map(sources.map((s) => [s.n, s])));

export function renderRich(text, sources = []) {
  const byN = new Map(sources.map((src) => [src.n, src]));
  const frag = document.createDocumentFragment();
  for (const block of parseRich(text)) {
    frag.append(block.type === 'ul'
      ? h('ul', {}, block.items.map((tokens) => h('li', {}, renderTokens(tokens, byN))))
      : h('p', {}, renderTokens(block.tokens, byN)));
  }
  return frag;
}

export function sourcesList(sources) {
  if (!sources?.length) return null;
  return h('div', { class: 'sources' }, h('strong', { text: 'Sources' }),
    h('ol', {}, sources.map((src) => h('li', {}, externalLink(safeUrl(src.uri), src.title)))));
}

/**
 * Google Search suggestions, required when showing grounded answers. Served from our own
 * /api/suggestions page with its own tight CSP, inside a sandboxed iframe with no scripts.
 */
export function searchFrame(url) {
  if (!url || !url.startsWith('/api/suggestions/')) return null;
  return h('iframe', {
    class: 'search-chips',
    title: 'Google Search suggestions',
    src: url,
    sandbox: 'allow-popups allow-popups-to-escape-sandbox',
    loading: 'lazy',
  });
}
