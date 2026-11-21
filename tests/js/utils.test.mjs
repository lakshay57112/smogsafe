// Unit tests for the frontend's pure helpers. Run with: node --test tests/js/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  clamp, debounce, fmt, hourLabel, parseInline, parseRich, plural, safeUrl, stripCitations, todayStr,
} from '../../static/js/utils.js';

test('fmt uses Indian digit grouping and limits decimals', () => {
  assert.equal(fmt(123456), '1,23,456');
  assert.equal(fmt(7.456, 1), '7.5');
  assert.equal(fmt(null), '0');
});

test('clamp and plural', () => {
  assert.equal(clamp(12, 0, 10), 10);
  assert.equal(clamp(-3, 0, 10), 0);
  assert.equal(plural(1, 'pledge', 'pledges'), 'pledge');
  assert.equal(plural(3, 'pledge', 'pledges'), 'pledges');
});

test('hourLabel reads clock time without timezone shifts', () => {
  assert.equal(hourLabel('2026-11-21T00:00'), '12 AM');
  assert.equal(hourLabel('2026-11-21T15:00:00'), '3 PM');
  assert.equal(hourLabel('2026-11-21T12:00'), '12 PM');
  assert.equal(hourLabel('bad'), '');
});

test('todayStr returns an ISO date', () => {
  assert.equal(todayStr(new Date('2026-11-21T10:00:00Z')), '2026-11-21');
});

test('safeUrl only allows http(s)', () => {
  assert.equal(safeUrl('https://cpcb.nic.in/x'), 'https://cpcb.nic.in/x');
  assert.equal(safeUrl('javascript:alert(1)'), '#');
  assert.equal(safeUrl('data:text/html,hi'), '#');
  assert.equal(safeUrl('not a url'), '#');
});

test('parseInline finds bold text and citations', () => {
  assert.deepEqual(parseInline('Saves **6.9 kg** a week.[1]'), [
    { type: 'text', value: 'Saves ' },
    { type: 'strong', value: '6.9 kg' },
    { type: 'text', value: ' a week.' },
    { type: 'cite', value: 1 },
  ]);
});

test('parseRich groups bullets into lists and strips headings', () => {
  const blocks = parseRich('## Tips\n- Shut windows\n* Wet mop\n\nStay safe.');
  assert.equal(blocks.length, 3);
  assert.deepEqual(blocks[0], { type: 'p', tokens: [{ type: 'text', value: 'Tips' }] });
  assert.equal(blocks[1].type, 'ul');
  assert.equal(blocks[1].items.length, 2);
  assert.equal(blocks[2].type, 'p');
  assert.deepEqual(parseRich(''), []);
});

test('parseRich never produces HTML: tags stay plain text', () => {
  const [block] = parseRich('<img src=x onerror=alert(1)>');
  assert.deepEqual(block.tokens, [{ type: 'text', value: '<img src=x onerror=alert(1)>' }]);
});

test('stripCitations removes [n] markers', () => {
  assert.equal(stripCitations('Metro helps.[1][2]'), 'Metro helps.');
});

test('debounce only runs the last call', async () => {
  const calls = [];
  const fn = debounce((x) => calls.push(x), 20);
  fn(1);
  fn(2);
  fn(3);
  await new Promise((r) => setTimeout(r, 50));
  assert.deepEqual(calls, [3]);
});
