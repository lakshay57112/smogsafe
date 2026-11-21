// What-if calculators. All maths runs on the server's tested impact engine.

import { api } from './api.js';
import { MODE_LABELS, POLLUTING_MODES } from './constants.js';
import { $, errorBlock, fill, h, icon } from './dom.js';
import { state } from './store.js';
import { clamp, debounce, fmt } from './utils.js';

function barCompare(rows, unit) {
  const max = Math.max(...rows.map((r) => r.value), 0.0001);
  return h('div', { class: 'bar-compare' }, rows.map((r) => {
    const bar = h('div', { class: `bar-fill ${r.after ? 'after' : ''}` });
    bar.style.width = `${clamp((r.value / max) * 100, 2, 100)}%`;
    return h('div', { class: 'bar-line' },
      h('span', { text: r.label }),
      h('div', { class: 'bar-track', role: 'presentation' }, bar),
      h('span', { text: `${fmt(r.value, r.value < 10 ? 1 : 0)} ${unit}` }));
  }));
}

const mathDetails = (...lines) =>
  h('details', { class: 'math' }, h('summary', { text: 'Show the maths' }), ...lines);

function renderCommute(box, r, fromMode, toMode) {
  const saves = r.co2_saved_year_kg >= 0;
  fill(box,
    h('p', { class: 'big-stat', text: saves ? `${fmt(r.co2_saved_year_kg)} kg CO₂ saved a year` : `${fmt(-r.co2_saved_year_kg)} kg more CO₂ a year` }),
    h('p', { text: saves ? `That's ${r.reduction_pct}% less for this commute, about ${fmt(r.co2_saved_month_kg)} kg a month.` : 'This switch increases emissions.' }),
    barCompare([
      { label: MODE_LABELS[fromMode], value: r.co2_before_week_kg },
      { label: MODE_LABELS[toMode], value: r.co2_after_week_kg, after: true },
    ], 'kg/wk'),
    saves
      ? h('p', {}, icon('🏙️'), 'If 1,000 people in your city did this: ',
        h('strong', { text: `${fmt(r.if_1000_people_tonnes_year)} tonnes CO₂ a year` }), ', and fewer engines idling in the smog.')
      : null,
    mathDetails(h('code', { class: 'formula', text: r.math })));
}

const runCommute = debounce(async () => {
  const f = $('#commute-calc');
  $('#c-km-out').textContent = f.km_one_way.value;
  $('#c-days-out').textContent = f.days_per_week.value;
  const box = $('#commute-result');
  if (f.from_mode.value === f.to_mode.value) {
    fill(box, h('p', { class: 'muted', text: 'Pick two different modes to compare.' }));
    return;
  }
  try {
    const r = await api('/api/impact/commute', {
      method: 'POST',
      body: {
        from_mode: f.from_mode.value,
        to_mode: f.to_mode.value,
        km_one_way: Number(f.km_one_way.value),
        days_per_week: Number(f.days_per_week.value),
      },
    });
    renderCommute(box, r, f.from_mode.value, f.to_mode.value);
  } catch (e) {
    fill(box, errorBlock(e.message));
  }
}, 250);

function renderExposure(box, r) {
  const better = r.exposure_cut_pct >= 0;
  fill(box,
    h('p', { class: 'big-stat', text: better ? `${r.exposure_cut_pct}% less smog breathed` : `${-r.exposure_cut_pct}% more smog breathed` }),
    barCompare([
      { label: 'Before', value: r.dose_before_ug },
      { label: 'After', value: r.dose_after_ug, after: true },
    ], 'µg'),
    better && r.cigarettes_avoided > 0
      ? h('p', {}, icon('🚬'), 'About ', h('strong', { text: `${fmt(r.cigarettes_avoided, 2)} cigarettes` }), ' of smoke avoided this session.')
      : null,
    mathDetails(h('p', { text: r.explanation }), h('code', { class: 'formula', text: r.math })));
}

export const runExposure = debounce(async () => {
  const f = $('#exposure-calc');
  $('#e-minutes-out').textContent = f.minutes.value;
  const box = $('#exposure-result');
  const pm = Number(f.pm25.value);
  if (!(pm >= 0)) return;
  try {
    const r = await api('/api/impact/exposure', {
      method: 'POST',
      body: {
        pm25: clamp(pm, 0, 2000),
        minutes: Number(f.minutes.value),
        activity: f.activity.value,
        from_setting: f.from_setting.value,
        to_setting: f.to_setting.value,
        from_mask: 'none',
        to_mask: f.to_mask.value,
      },
    });
    renderExposure(box, r);
  } catch (e) {
    fill(box, errorBlock(e.message));
  }
}, 250);

function modeOptions(selected) {
  return Object.entries(MODE_LABELS).map(([value, label]) => {
    const option = h('option', { value, text: label });
    option.selected = value === selected;
    return option;
  });
}

export function initCalculators() {
  const hhMode = state.household?.commute_mode;
  fill($('#c-from'), modeOptions(POLLUTING_MODES.includes(hhMode) ? hhMode : 'car_solo'));
  fill($('#c-to'), modeOptions('metro'));
  if (state.household?.commute_km) $('#c-km').value = clamp(Math.round(state.household.commute_km), 1, 50);
  for (const [formId, run] of [['#commute-calc', runCommute], ['#exposure-calc', runExposure]]) {
    $(formId).addEventListener('input', run);
    $(formId).addEventListener('submit', (e) => e.preventDefault());
  }
  runCommute();
  runExposure();
}
