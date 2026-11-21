// "How we calculate" dialog: every factor and source behind the impact numbers.

import { api } from './api.js';
import { $, errorBlock, externalLink, fill, h } from './dom.js';
import { state } from './store.js';
import { fmt, safeUrl } from './utils.js';

function factorTable(caption, rows, headers) {
  return h('table', { class: 'factor-table' },
    h('caption', { class: 'sr-only', text: caption }),
    h('thead', {}, h('tr', {}, headers.map((t) => h('th', { scope: 'col', text: t })))),
    h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c) => h('td', { text: c }))))));
}

function renderFactors(f) {
  const labelled = (values, labels) => Object.entries(values).map(([k, v]) => [labels ? labels[k] : k, v]);
  return [
    h('p', {}, h('strong', { text: 'Cigarette rule: ' }),
      `breathing ${f.cigarette_pm25_ugm3} µg/m³ of PM2.5 for a day is roughly as harmful as one cigarette. `
      + `An adult breathes about ${f.daily_air_m3} m³ of air a day, so one cigarette ≈ ${fmt(f.ug_per_cigarette)} µg of PM2.5 inhaled.`),
    h('p', {}, h('strong', { text: 'Smog breathed' }),
      ' = PM2.5 outside × share that reaches you (setting × mask) × breathing rate × time.'),
    h('h3', { class: 'h3', text: 'Breathing rate (m³ per hour)' }),
    factorTable('Breathing rates', labelled(f.breathing_m3_per_hour), ['Activity', 'm³/hour']),
    h('h3', { class: 'h3', text: 'Share of outdoor PM2.5 reaching you' }),
    factorTable('Setting factors', labelled(f.setting_factor, f.setting_labels), ['Setting', 'Share']),
    factorTable('Mask factors', labelled(f.mask_factor, f.mask_labels), ['Mask', 'Share that gets through']),
    h('h3', { class: 'h3', text: 'Commute emissions (kg CO₂ per passenger-km)' }),
    factorTable('Commute emissions', labelled(f.co2_kg_per_pkm, f.mode_labels), ['Mode', 'kg CO₂/km']),
    h('p', { class: 'muted small', text: 'All values are rounded estimates meant to compare choices, not exact measurements.' }),
    h('h3', { class: 'h3', text: 'Sources' }),
    h('ul', {}, f.sources.map((src) => h('li', {}, externalLink(safeUrl(src.url), src.label)))),
  ];
}

export async function openFactors() {
  const dlg = $('#factors-dialog');
  if (typeof dlg.showModal === 'function') dlg.showModal();
  if (state.factors) return;
  try {
    state.factors = await api('/api/impact/factors');
    fill($('#factors-body'), renderFactors(state.factors));
  } catch (e) {
    fill($('#factors-body'), errorBlock(e.message));
  }
}
