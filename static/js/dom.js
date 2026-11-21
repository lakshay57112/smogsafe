// Small DOM helpers. All text goes in through textContent, never innerHTML.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const isEmpty = (v) => v === null || v === undefined || v === false;

/**
 * Create an element: h('p', { class: 'note', text: 'Hi' }, child1, child2).
 * Keys starting with "on" become event listeners; everything else is an attribute.
 */
function setAttr(el, key, value) {
  if (isEmpty(value)) return;
  if (key === 'class') el.className = value;
  else if (key === 'text') el.textContent = value;
  else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
  else el.setAttribute(key, value === true ? '' : String(value));
}

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([key, value]) => setAttr(el, key, value));
  children.flat(Infinity)
    .filter((child) => !isEmpty(child))
    .forEach((child) => el.append(child instanceof Node ? child : document.createTextNode(String(child))));
  return el;
}

const SVG_NS = 'http://www.w3.org/2000/svg';

/** Same as h() but for SVG elements. */
export function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'text') el.textContent = value;
    else el.setAttribute(key, String(value));
  }
  children.flat().forEach((c) => c && el.append(c));
  return el;
}

/** Replace an element's children, skipping null/false entries. */
export function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => !isEmpty(k)));
}

let toastTimer;
export function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3500);
}

export function errorBlock(message, retry) {
  return h('div', { class: 'notice', role: 'alert' },
    h('p', { text: `⚠️ ${message}` }),
    retry ? h('button', { type: 'button', class: 'btn btn-ghost btn-sm', onclick: retry, text: 'Try again' }) : null);
}

/** Grey loading bars. Width is set through the CSSOM, which the strict CSP allows. */
export function skeletonLines(n = 3) {
  return Array.from({ length: n }, (_, i) => {
    const line = h('div', { class: 'skeleton skeleton-line', 'aria-hidden': 'true' });
    line.style.width = `${90 - i * 15}%`;
    return line;
  });
}

/** Emoji are decoration: hidden from screen readers so only the words are read out. */
export const icon = (emoji) => h('span', { 'aria-hidden': 'true', text: `${emoji} ` });

export const badge = (cls, emoji, text) => h('span', { class: cls, role: 'listitem' }, icon(emoji), text);

export const externalLink = (href, text, extra = {}) =>
  h('a', { href, target: '_blank', rel: 'noopener noreferrer', text, ...extra });
