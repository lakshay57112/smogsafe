// "Air right now" card, 24-hour forecast chart and cleanest/smoggiest windows.

import { api } from './api.js';
import { runExposure } from './calculators.js';
import { CAT_COLORS, CPCB_URL } from './constants.js';
import { $, errorBlock, externalLink, fill, h, s, skeletonLines } from './dom.js';
import { restorePlanIfFresh } from './plan.js';
import { state } from './store.js';
import { clamp, fmt, hourLabel } from './utils.js';

const INDIA_PM25_LIMIT = 60; // µg/m³, 24-hour national standard

export async function loadAir() {
  if (!state.location) return;
  const card = $('#aqi-card');
  card.setAttribute('aria-busy', 'true');
  fill($('#aqi-body'), ...skeletonLines(4));
  fill($('#forecast-figure'), h('div', { class: 'skeleton skeleton-chart', 'aria-hidden': 'true' }));
  fill($('#windows'));
  const { lat, lon } = state.location;
  try {
    const air = await api(`/api/air?lat=${lat.toFixed(4)}&lon=${lon.toFixed(4)}`, { timeout: 20000 });
    state.air = air;
    renderAir(air);
    renderChart(air);
    renderWindows(air);
    $('#data-source').textContent = air.source_label;
    const pm = air.avg24.pm2_5 ?? air.current.pm2_5;
    if (pm != null) $('#e-pm').value = Math.round(pm);
    runExposure();
    restorePlanIfFresh();
  } catch (e) {
    fill($('#aqi-body'), errorBlock(e.message, loadAir));
    fill($('#forecast-figure'), h('p', { class: 'muted', text: 'Forecast unavailable right now.' }));
  } finally {
    card.setAttribute('aria-busy', 'false');
  }
}

function aqiDial(aqi) {
  const dial = h('div', { class: 'aqi-dial', role: 'img', 'aria-label': `Indian AQI ${aqi.value}, ${aqi.category}` },
    h('div', {}, h('span', { class: 'aqi-number', text: aqi.value }), h('span', { class: 'aqi-label', text: 'Indian AQI' })));
  dial.style.setProperty('--dial', aqi.color);
  dial.style.setProperty('--dial-ink', aqi.text_color);
  return dial;
}

function sourceNote(air) {
  const isDemo = air.source === 'demo';
  const origin = air.is_model_estimate ? 'Model estimate' : 'Live reading';
  return h('p', { class: 'source-note' },
    isDemo ? h('span', { class: 'badge-demo', text: 'DEMO DATA' }) : null,
    isDemo ? ' Sample winter-smog data for demos. ' : `${origin} from ${air.source_label}. `,
    'Official station readings: ', externalLink(CPCB_URL, 'CPCB'), '.');
}

function renderAir(air) {
  const a = air.india_aqi;
  document.documentElement.dataset.aqi = a.category_key;
  fill($('#aqi-body'),
    h('div', { class: 'aqi-main' }, aqiDial(a),
      h('div', {},
        h('p', { class: 'aqi-cat', text: a.category }),
        h('p', { class: 'aqi-dominant' }, 'Main pollutant: ', h('strong', { text: a.dominant_label })))),
    air.cigarettes_today != null
      ? h('div', { class: 'cig' }, h('span', { 'aria-hidden': 'true', text: '🚬' }),
        h('p', { class: 'cig-text' }, 'Breathing this air all day is like smoking about ',
          h('strong', { text: `${fmt(air.cigarettes_today, 1)} cigarettes` }), '.'))
      : null,
    h('p', { class: 'aqi-health', text: a.health }),
    h('ul', { class: 'aqi-meta' },
      h('li', { text: `PM2.5 now: ${fmt(air.current.pm2_5)} µg/m³` }),
      h('li', { text: `24-h average: ${fmt(air.avg24.pm2_5)} µg/m³` }),
      h('li', { text: `Updated ${hourLabel(air.updated_local)}` })),
    sourceNote(air));
}

/** Chart geometry for a given width: padding, scale and bar width. */
function chartLayout(width, points) {
  const W = Math.round(clamp(width || 640, 300, 760));
  const H = W < 480 ? 210 : 230;
  const pad = { l: 34, r: 8, t: 22, b: 30 };
  const maxVal = Math.max(100, ...points.map((p) => p.pm2_5)) * 1.12;
  const innerH = H - pad.t - pad.b;
  return {
    W, H, pad, maxVal, innerH,
    labelEvery: W < 480 ? 6 : 3,
    bw: (W - pad.l - pad.r) / points.length,
    y: (v) => pad.t + innerH * (1 - v / maxVal),
  };
}

function gridlines({ W, pad, maxVal, y }) {
  const step = maxVal > 300 ? 100 : 50;
  const lines = [];
  for (let v = 0; v <= maxVal; v += step) {
    lines.push(
      s('line', { x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: '#e3ebe7', 'stroke-width': 1 }),
      s('text', { x: pad.l - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 10, fill: '#5b6b65', text: v }),
    );
  }
  return lines;
}

function cleanestHighlight({ pad, bw, innerH }, points, best) {
  const i = best ? points.findIndex((p) => p.time.slice(0, 16) === best.start.slice(0, 16)) : -1;
  if (i < 0) return [];
  return [
    s('rect', {
      x: pad.l + i * bw - 1, y: pad.t - 4, width: bw * 2 + 2, height: innerH + 4,
      fill: 'rgba(16,185,129,0.12)', stroke: '#059669', 'stroke-dasharray': '4 3', rx: 6,
    }),
    s('text', {
      x: pad.l + i * bw + bw, y: pad.t - 8, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 700,
      fill: '#047857', text: 'Cleanest',
    }),
  ];
}

function bars({ H, pad, bw, innerH, y, labelEvery }, points) {
  return points.flatMap((p, i) => {
    const top = y(p.pm2_5);
    const bar = s('rect', {
      x: pad.l + i * bw + 1.5, y: top, width: Math.max(bw - 3, 2), height: Math.max(pad.t + innerH - top, 1),
      rx: 3, fill: CAT_COLORS[p.category_key] || '#94a3b8',
    }, s('title', { text: `${p.hour_label}: PM2.5 ${fmt(p.pm2_5)} µg/m³` }));
    const label = i % labelEvery === 0
      ? s('text', {
        x: pad.l + i * bw + bw / 2, y: H - 10, 'text-anchor': 'middle', 'font-size': 10.5, fill: '#5b6b65', text: p.hour_label,
      })
      : null;
    return label ? [bar, label] : [bar];
  });
}

function limitLine({ W, pad, y }) {
  const limitY = y(INDIA_PM25_LIMIT);
  return [
    s('line', { x1: pad.l, x2: W - pad.r, y1: limitY, y2: limitY, stroke: '#0f766e', 'stroke-width': 1.5, 'stroke-dasharray': '6 4' }),
    s('rect', { x: pad.l + 4, y: limitY - 17, width: 132, height: 15, rx: 4, fill: 'rgba(255,255,255,0.92)' }),
    s('text', { x: pad.l + 8, y: limitY - 6, 'font-size': 10.5, 'font-weight': 700, fill: '#0f766e', text: "India's 24-h limit (60)" }),
  ];
}

/** Screen-reader version of the chart. */
function chartTable(points) {
  return h('table', { class: 'sr-only' },
    h('caption', { text: 'Hourly PM2.5 forecast' }),
    h('thead', {}, h('tr', {}, h('th', { scope: 'col', text: 'Hour' }), h('th', { scope: 'col', text: 'PM2.5 (µg/m³)' }))),
    h('tbody', {}, points.map((p) => h('tr', {}, h('td', { text: p.hour_label }), h('td', { text: fmt(p.pm2_5) })))));
}

/** Bar chart of hourly PM2.5, sized to its container so labels stay readable on phones. */
export function renderChart(air) {
  const fig = $('#forecast-figure');
  const points = air.forecast.filter((p) => p.pm2_5 != null);
  if (!points.length) {
    fill(fig, h('p', { class: 'muted', text: 'Forecast unavailable.' }));
    return;
  }
  const layout = chartLayout(fig.clientWidth, points);
  const { best_window: best, worst_window: worst } = air;
  const values = points.map((p) => p.pm2_5);
  const desc = `Hourly PM2.5 ranges from ${fmt(Math.min(...values))} to ${fmt(Math.max(...values))} µg/m³.`
    + (best ? ` Cleanest window: ${best.label}.` : '') + (worst ? ` Smoggiest: ${worst.label}.` : '');
  const svgEl = s('svg', { viewBox: `0 0 ${layout.W} ${layout.H}`, role: 'img', 'aria-labelledby': 'chart-title chart-desc' },
    s('title', { id: 'chart-title', text: 'PM2.5 forecast for the next 24 hours' }),
    s('desc', { id: 'chart-desc', text: desc }),
    gridlines(layout), cleanestHighlight(layout, points, best), bars(layout, points), limitLine(layout));
  fill(fig, svgEl,
    h('figcaption', { text: "Hourly PM2.5, coloured by AQI band. The dashed line is India's 24-hour safe limit for PM2.5." }),
    chartTable(points));
}

function windowChip(kind, emoji, ...content) {
  return h('p', { class: `window-chip ${kind}` }, h('span', { 'aria-hidden': 'true', text: emoji }), h('span', {}, ...content));
}

function renderWindows(air) {
  const { best_window: best, worst_window: worst } = air;
  const now = air.current.pm2_5;
  fill($('#windows'),
    best && now != null && now <= best.avg_pm2_5 * 1.05
      ? windowChip('now', '🟢', h('strong', { text: 'Right now' }), ' is one of the cleanest times. Good time for errands.')
      : null,
    best ? windowChip('best', '✅', 'Cleanest: ', h('strong', { text: best.label }), ` · PM2.5 ~${fmt(best.avg_pm2_5)}`) : null,
    worst
      ? windowChip('worst', '⚠️', 'Smoggiest: ', h('strong', { text: worst.label }), ` · ~${fmt(worst.avg_pm2_5)}. Keep windows shut.`)
      : null);
}
