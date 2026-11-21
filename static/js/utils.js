// Pure helpers with no DOM access, so they can be unit-tested in Node (tests/js).

/** Format a number the Indian way (1,23,456), with up to `digits` decimals. */
export const fmt = (n, digits = 0) =>
  Number(n ?? 0).toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: 0 });

export const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

export const todayStr = (date = new Date()) => date.toISOString().slice(0, 10);

export const plural = (n, one, many) => (n === 1 ? one : many);

/** Delay calls until `ms` have passed without another call (used for typing and sliders). */
export function debounce(fn, ms = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

/** "2026-11-21T15:00" -> "3 PM" (reads the clock time as written, no timezone shifts). */
export function hourLabel(isoLocal) {
  const match = /T(\d{2}):/.exec(String(isoLocal));
  if (!match) return '';
  const hr = Number(match[1]);
  return `${hr % 12 || 12} ${hr < 12 ? 'AM' : 'PM'}`;
}

/** Only allow http(s) links; anything else (javascript:, data:) becomes "#". */
export function safeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : '#';
  } catch {
    return '#';
  }
}

export const stripCitations = (text) => String(text).replace(/\[\d+\]/g, '');

/**
 * Split one line into text, **bold** and [n] citation tokens.
 * @returns {{type: 'text'|'strong'|'cite', value: string|number}[]}
 */
export function parseInline(text) {
  const tokens = [];
  const re = /(\*\*[^*]+\*\*|\[\d+\])/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) tokens.push({ type: 'text', value: text.slice(last, m.index) });
    const tok = m[0];
    tokens.push(tok.startsWith('**')
      ? { type: 'strong', value: tok.slice(2, -2) }
      : { type: 'cite', value: Number(tok.slice(1, -1)) });
    last = m.index + tok.length;
  }
  if (last < text.length) tokens.push({ type: 'text', value: text.slice(last) });
  return tokens;
}

/**
 * Turn a short AI answer into paragraphs and bullet lists (a tiny, safe markdown subset).
 * @returns {({type: 'p', tokens: object[]} | {type: 'ul', items: object[][]})[]}
 */
export function parseRich(text) {
  const blocks = [];
  let list = null;
  for (const raw of String(text ?? '').split('\n')) {
    const line = raw.trim().replace(/^#{1,6}\s+/, '');
    if (!line) {
      list = null;
      continue;
    }
    const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (bullet) {
      if (!list) {
        list = { type: 'ul', items: [] };
        blocks.push(list);
      }
      list.items.push(parseInline(bullet[1]));
    } else {
      list = null;
      blocks.push({ type: 'p', tokens: parseInline(line) });
    }
  }
  return blocks;
}
