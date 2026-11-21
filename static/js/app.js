// SmogSafe frontend: plain JavaScript, no framework or build step.
// Every piece of server/AI text is inserted with textContent (never innerHTML).

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const DEFAULT_LOCATION = { lat: 28.6139, lon: 77.209, name: 'New Delhi', state: 'Delhi' };

const CAT_COLORS = {
  good: '#2E7D32', satisfactory: '#7CB342', moderate: '#F9C623',
  poor: '#EF6C00', very_poor: '#C62828', severe: '#5D1A1A',
};
const TIME_ICONS = { Morning: '🌅', Afternoon: '☀️', Evening: '🌆', Night: '🌙', Anytime: '⏱️' };
const CATEGORY_ICONS = { commute: '🚇', outdoor: '🚶', indoor: '🏠', cooking: '🍳', health: '😷', community: '🤝' };
const AGE_LABELS = { infant: 'Baby', child: 'Child', teen: 'Teen', adult: 'Adult', senior: 'Senior' };
const COND_LABELS = {
  asthma: 'asthma', copd: 'lung disease', heart: 'heart condition',
  pregnant: 'pregnant', allergies: 'allergies', diabetes: 'diabetes',
};
const RISK_LABELS = { low: 'Low risk', moderate: 'Moderate risk', high: 'High risk', very_high: 'Very high risk' };
const MODE_LABELS = {
  car_solo: 'Car (alone)', car_pool: 'Carpool (2 people)', cab: 'Cab / taxi', auto: 'Auto-rickshaw',
  two_wheeler: 'Petrol two-wheeler', e_two_wheeler: 'Electric two-wheeler', bus: 'Bus', metro: 'Metro',
  walk_cycle: 'Walk / cycle', work_from_home: 'Work from home',
};
const POLLUTING_MODES = ['car_solo', 'car_pool', 'cab', 'auto', 'two_wheeler'];
const LANG_NAMES = { en: 'English', hi: 'Hindi', hinglish: 'Hinglish' };
const DEFAULT_CHECKLIST = [
  { item: 'Wet-mop floors instead of sweeping', why: 'A dry broom kicks settled dust back into the air.' },
  { item: 'Keep windows shut during the smoggiest hours', why: 'Air out the house in the cleanest window instead.' },
  { item: 'No incense, dhoop or mosquito coils indoors', why: 'They add smoke right where you breathe.' },
  { item: 'Run the kitchen exhaust while cooking', why: 'It removes cooking particles at the source.' },
];

// ---------- tiny helpers ----------

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
}

const SVG_NS = 'http://www.w3.org/2000/svg';
function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'text') el.textContent = value;
    else el.setAttribute(key, String(value));
  }
  children.flat().forEach((c) => c && el.append(c));
  return el;
}

const store = {
  get(key, fallback) {
    try {
      const raw = localStorage.getItem(`ss_${key}`);
      return raw ? JSON.parse(raw) : fallback;
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(`ss_${key}`, JSON.stringify(value));
    } catch {
      /* storage can be blocked in private mode; the app still works */
    }
  },
};

const fmt = (n, digits = 0) =>
  Number(n ?? 0).toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
const todayStr = () => new Date().toISOString().slice(0, 10);
const debounce = (fn, ms = 300) => {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
};
function hourLabel(isoLocal) {
  const hr = Number(String(isoLocal).slice(11, 13));
  if (Number.isNaN(hr)) return '';
  return `${hr % 12 || 12} ${hr < 12 ? 'AM' : 'PM'}`;
}
function safeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : '#';
  } catch {
    return '#';
  }
}

function newDeviceId() {
  const id = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`)
    .replace(/[^A-Za-z0-9-]/g, '')
    .slice(0, 60);
  store.set('device', id);
  return id;
}

// ---------- state ----------

const state = {
  location: store.get('location', null),
  household: store.get('household', null),
  members: store.get('members', []),
  lang: store.get('lang', 'en'),
  deviceId: store.get('device', null) || newDeviceId(),
  checks: store.get('checks', { date: todayStr(), done: {} }),
  air: null,
  plan: null,
  chat: [],
  factors: null,
  communityFor: null,
  advisoriesFor: null,
};
if (state.checks.date !== todayStr()) state.checks = { date: todayStr(), done: {} };

const locKey = () => (state.location ? `${state.location.lat.toFixed(2)},${state.location.lon.toFixed(2)}` : '');

// ---------- API ----------

async function api(path, { method = 'GET', body, timeout = 60000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      let msg = `Something went wrong (${res.status}). Please try again.`;
      if (typeof data.detail === 'string') msg = data.detail;
      else if (res.status === 422) msg = 'Some details look invalid. Please check and try again.';
      throw new Error(msg);
    }
    return data;
  } catch (err) {
    if (err.name === 'AbortError') throw new Error('This is taking too long. Please try again.');
    if (err instanceof TypeError) throw new Error('Could not reach SmogSafe. Check your internet connection.');
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

let toastTimer;
function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3500);
}

function errorBlock(message, retry) {
  return h('div', { class: 'notice', role: 'alert' },
    h('p', { text: `⚠️ ${message}` }),
    retry ? h('button', { type: 'button', class: 'btn btn-ghost btn-sm', onclick: retry, text: 'Try again' }) : null);
}

const skeletonLines = (n = 3) => Array.from({ length: n }, (_, i) =>
  h('div', { class: 'skeleton skeleton-line', style: `width:${90 - i * 15}%`, 'aria-hidden': 'true' }));

// ---------- location ----------

function applyLocationUI() {
  const name = state.location?.name || 'your area';
  $('#location-name').textContent = state.location ? name : 'Find my air';
  $('#air-place').textContent = name;
  $('#circle-city').textContent = name;
}

function setLocation(loc) {
  state.location = loc;
  store.set('location', loc);
  state.plan = null;
  state.chat = [];
  applyLocationUI();
  fill($('#plan-output'), );
  loadAir();
  const tab = currentTab();
  if (tab === 'circle') {
    loadCircle(true);
    loadAdvisories(true);
  }
}

function detectLocation({ silent = false } = {}) {
  if (!('geolocation' in navigator)) {
    if (silent) setLocation(DEFAULT_LOCATION);
    else {
      toast('Location is not available here. Please search your city.');
      openCityDialog();
    }
    return;
  }
  fill($('#aqi-body'), h('p', { class: 'muted', text: 'Finding your location…' }), ...skeletonLines(2));
  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      const { latitude: lat, longitude: lon } = pos.coords;
      let place = { name: 'Your location', state: '' };
      try {
        place = await api(`/api/geocode/reverse?lat=${lat.toFixed(4)}&lon=${lon.toFixed(4)}`, { timeout: 10000 });
      } catch {
        /* keep the generic name */
      }
      setLocation({ lat, lon, name: place.name || 'Your location', state: place.state || '' });
    },
    () => {
      if (silent) {
        setLocation(DEFAULT_LOCATION);
        toast('Showing New Delhi. Tap 📍 at the top to choose your city.');
      } else {
        toast('Could not get your location. Please search your city instead.');
        openCityDialog();
      }
    },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 30 * 60 * 1000 },
  );
}

function openCityDialog() {
  const dlg = $('#city-dialog');
  if (typeof dlg.showModal === 'function' && !dlg.open) dlg.showModal();
  $('#city-input').focus();
}

const searchCities = debounce(async (q) => {
  const list = $('#city-results');
  if (q.trim().length < 2) {
    fill(list, );
    return;
  }
  fill(list, h('li', { class: 'muted', text: 'Searching…' }));
  try {
    const { results } = await api(`/api/geocode/search?q=${encodeURIComponent(q.trim())}`, { timeout: 10000 });
    if (!results.length) {
      fill(list, h('li', { class: 'muted', text: 'No Indian city found with that name.' }));
      return;
    }
    fill(list, ...results.map((r) => h('li', {},
      h('button', {
        type: 'button',
        onclick: () => {
          $('#city-dialog').close();
          setLocation({ lat: r.lat, lon: r.lon, name: r.name, state: r.state });
        },
      }, h('strong', { text: r.name }), r.state ? ` · ${r.district && r.district !== r.name ? `${r.district}, ` : ''}${r.state}` : ''))));
  } catch (e) {
    fill(list, h('li', { class: 'form-error', text: e.message }));
  }
}, 300);

// ---------- air card + forecast ----------

async function loadAir() {
  if (!state.location) return;
  const card = $('#aqi-card');
  card.setAttribute('aria-busy', 'true');
  fill($('#aqi-body'), ...skeletonLines(4));
  fill($('#forecast-figure'), h('div', { class: 'skeleton skeleton-chart', 'aria-hidden': 'true' }));
  fill($('#windows'), );
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

function renderAir(air) {
  const a = air.india_aqi;
  document.documentElement.dataset.aqi = a.category_key;
  const dial = h('div', { class: 'aqi-dial', role: 'img', 'aria-label': `Indian AQI ${a.value}, ${a.category}` },
    h('div', {}, h('span', { class: 'aqi-number', text: a.value }), h('span', { class: 'aqi-label', text: 'Indian AQI' })));
  dial.style.setProperty('--dial', a.color);
  dial.style.setProperty('--dial-ink', a.text_color);

  const isDemo = air.source === 'demo';
  fill($('#aqi-body'), 
    h('div', { class: 'aqi-main' }, dial,
      h('div', {},
        h('p', { class: 'aqi-cat', text: a.category }),
        h('p', { class: 'aqi-dominant' }, 'Main pollutant: ', h('strong', { text: a.dominant_label })))),
    air.cigarettes_today != null
      ? h('div', { class: 'cig' }, h('span', { 'aria-hidden': 'true', text: '🚬' }),
        h('p', { style: 'margin:0' }, 'Breathing this air all day is like smoking about ',
          h('strong', { text: `${fmt(air.cigarettes_today, 1)} cigarettes` }), '.'))
      : null,
    h('p', { class: 'aqi-health', text: a.health }),
    h('ul', { class: 'aqi-meta' },
      h('li', { text: `PM2.5 now: ${fmt(air.current.pm2_5)} µg/m³` }),
      h('li', { text: `24-h average: ${fmt(air.avg24.pm2_5)} µg/m³` }),
      h('li', { text: `Updated ${hourLabel(air.updated_local)}` })),
    h('p', { class: 'source-note' },
      isDemo ? h('span', { class: 'badge-demo', text: 'DEMO DATA' }) : null,
      isDemo ? ' Sample winter-smog data for demos. ' : `${air.is_model_estimate ? 'Model estimate' : 'Live reading'} from ${air.source_label}. `,
      'Official station readings: ',
      h('a', { href: 'https://airquality.cpcb.gov.in/AQI_India/', target: '_blank', rel: 'noopener noreferrer', text: 'CPCB' }),
      '.'),
  );
}

function renderChart(air) {
  const fig = $('#forecast-figure');
  const pts = air.forecast.filter((p) => p.pm2_5 != null);
  if (!pts.length) {
    fill(fig, h('p', { class: 'muted', text: 'Forecast unavailable.' }));
    return;
  }
  const W = Math.round(clamp(fig.clientWidth || 640, 300, 760)); const H = W < 480 ? 210 : 230;
  const padL = 34; const padR = 8; const padT = 22; const padB = 30;
  const labelEvery = W < 480 ? 6 : 3;
  const maxVal = Math.max(100, ...pts.map((p) => p.pm2_5)) * 1.12;
  const innerH = H - padT - padB;
  const bw = (W - padL - padR) / pts.length;
  const y = (v) => padT + innerH * (1 - v / maxVal);
  const best = air.best_window;
  const worst = air.worst_window;

  const svgEl = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-labelledby': 'chart-title chart-desc' },
    s('title', { id: 'chart-title', text: 'PM2.5 forecast for the next 24 hours' }),
    s('desc', {
      id: 'chart-desc',
      text: `Hourly PM2.5 ranges from ${fmt(Math.min(...pts.map((p) => p.pm2_5)))} to ${fmt(Math.max(...pts.map((p) => p.pm2_5)))} µg/m³.`
        + (best ? ` Cleanest window: ${best.label}.` : '') + (worst ? ` Smoggiest: ${worst.label}.` : ''),
    }));

  // Gridlines
  const step = maxVal > 300 ? 100 : 50;
  for (let v = 0; v <= maxVal; v += step) {
    svgEl.append(s('line', { x1: padL, x2: W - padR, y1: y(v), y2: y(v), stroke: '#e3ebe7', 'stroke-width': 1 }));
    svgEl.append(s('text', { x: padL - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 10, fill: '#5b6b65', text: v }));
  }

  // Cleanest window highlight
  if (best) {
    const i = pts.findIndex((p) => p.time.slice(0, 16) === best.start.slice(0, 16));
    if (i >= 0) {
      svgEl.append(s('rect', {
        x: padL + i * bw - 1, y: padT - 4, width: bw * 2 + 2, height: innerH + 4,
        fill: 'rgba(16,185,129,0.12)', stroke: '#059669', 'stroke-dasharray': '4 3', rx: 6,
      }));
      svgEl.append(s('text', { x: padL + i * bw + bw, y: padT - 8, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 700, fill: '#047857', text: 'Cleanest' }));
    }
  }

  // Bars
  pts.forEach((p, i) => {
    const top = y(p.pm2_5);
    const bar = s('rect', {
      x: padL + i * bw + 1.5, y: top, width: Math.max(bw - 3, 2), height: Math.max(padT + innerH - top, 1),
      rx: 3, fill: CAT_COLORS[p.category_key] || '#94a3b8',
    });
    bar.append(s('title', { text: `${p.hour_label}: PM2.5 ${fmt(p.pm2_5)} µg/m³` }));
    svgEl.append(bar);
    if (i % labelEvery === 0) {
      svgEl.append(s('text', { x: padL + i * bw + bw / 2, y: H - 10, 'text-anchor': 'middle', 'font-size': 10.5, fill: '#5b6b65', text: p.hour_label }));
    }
  });

  // India's 24-hour PM2.5 standard
  svgEl.append(s('line', { x1: padL, x2: W - padR, y1: y(60), y2: y(60), stroke: '#0f766e', 'stroke-width': 1.5, 'stroke-dasharray': '6 4' }));
  svgEl.append(s('rect', { x: padL + 4, y: y(60) - 17, width: 132, height: 15, rx: 4, fill: 'rgba(255,255,255,0.92)' }));
  svgEl.append(s('text', { x: padL + 8, y: y(60) - 6, 'font-size': 10.5, 'font-weight': 700, fill: '#0f766e', text: "India's 24-h limit (60)" }));

  const table = h('table', { class: 'sr-only' },
    h('caption', { text: 'Hourly PM2.5 forecast' }),
    h('thead', {}, h('tr', {}, h('th', { scope: 'col', text: 'Hour' }), h('th', { scope: 'col', text: 'PM2.5 (µg/m³)' }))),
    h('tbody', {}, pts.map((p) => h('tr', {}, h('td', { text: p.hour_label }), h('td', { text: fmt(p.pm2_5) })))));

  fill(fig, svgEl,
    h('figcaption', { text: "Hourly PM2.5, coloured by AQI band. The dashed line is India's 24-hour safe limit for PM2.5." }),
    table);
}

function renderWindows(air) {
  const box = $('#windows');
  const chips = [];
  const now = air.current.pm2_5;
  const best = air.best_window;
  const worst = air.worst_window;
  if (best && now != null && now <= best.avg_pm2_5 * 1.05) {
    chips.push(h('p', { class: 'window-chip now' }, h('span', { 'aria-hidden': 'true', text: '🟢' }),
      h('span', {}, h('strong', { text: 'Right now' }), ' is one of the cleanest times. Good time for errands.')));
  }
  if (best) {
    chips.push(h('p', { class: 'window-chip best' }, h('span', { 'aria-hidden': 'true', text: '✅' }),
      h('span', {}, 'Cleanest: ', h('strong', { text: best.label }), ` · PM2.5 ~${fmt(best.avg_pm2_5)}`)));
  }
  if (worst) {
    chips.push(h('p', { class: 'window-chip worst' }, h('span', { 'aria-hidden': 'true', text: '⚠️' }),
      h('span', {}, 'Smoggiest: ', h('strong', { text: worst.label }), ` · ~${fmt(worst.avg_pm2_5)}. Keep windows shut.`)));
  }
  fill(box, ...chips);
}

// ---------- tabs ----------

const tabs = () => $$('[role="tab"]');
const currentTab = () => (tabs().find((t) => t.getAttribute('aria-selected') === 'true')?.id || 'tab-plan').replace('tab-', '');

function selectTab(tab, focus = false) {
  tabs().forEach((t) => {
    const selected = t === tab;
    t.setAttribute('aria-selected', String(selected));
    t.tabIndex = selected ? 0 : -1;
    $(`#${t.getAttribute('aria-controls')}`).hidden = !selected;
  });
  if (focus) tab.focus();
  onTabShown(tab.id.replace('tab-', ''));
}

function initTabs() {
  const list = tabs();
  list.forEach((tab, i) => {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('keydown', (e) => {
      let j = null;
      if (e.key === 'ArrowRight') j = (i + 1) % list.length;
      else if (e.key === 'ArrowLeft') j = (i - 1 + list.length) % list.length;
      else if (e.key === 'Home') j = 0;
      else if (e.key === 'End') j = list.length - 1;
      if (j !== null) {
        e.preventDefault();
        selectTab(list[j], true);
      }
    });
  });
  $$('[data-goto]').forEach((btn) => btn.addEventListener('click', () => selectTab($(`#tab-${btn.dataset.goto}`), true)));
}

function onTabShown(name) {
  if (name === 'family') renderFamilyAdvice();
  if (name === 'circle') {
    loadCircle();
    loadAdvisories();
  }
}

// ---------- household & members ----------

function readHousehold() {
  const f = $('#household-form');
  return {
    commute_mode: f.commute_mode.value,
    commute_km: clamp(parseFloat(f.commute_km.value) || 0, 0, 150),
    commute_days: clamp(parseInt(f.commute_days.value, 10) || 0, 0, 7),
    cooking_fuel: f.cooking_fuel.value,
    has_purifier: f.has_purifier.checked,
    near_busy_road: f.near_busy_road.checked,
    exercises_outdoors: f.exercises_outdoors.checked,
  };
}

function fillHousehold(hh) {
  const f = $('#household-form');
  f.commute_mode.value = hh.commute_mode;
  f.commute_km.value = hh.commute_km;
  f.commute_days.value = hh.commute_days;
  f.cooking_fuel.value = hh.cooking_fuel;
  f.has_purifier.checked = !!hh.has_purifier;
  f.near_busy_road.checked = !!hh.near_busy_road;
  f.exercises_outdoors.checked = !!hh.exercises_outdoors;
}

const householdPayload = () => ({ ...(state.household || readHousehold()), members: state.members });

function updateHouseholdSummary() {
  const hh = state.household;
  const n = state.members.length;
  $('#household-summary').textContent = hh
    ? `${MODE_LABELS[hh.commute_mode]}${hh.commute_km ? ` · ${hh.commute_km} km` : ''} · ${n} family member${n === 1 ? '' : 's'}${hh.has_purifier ? ' · purifier' : ''}`
    : 'Tell us a little so tips fit your life';
}

function renderMembers() {
  const list = $('#member-list');
  if (!state.members.length) {
    fill(list, h('li', { class: 'muted', text: 'No one added yet.' }));
    return;
  }
  fill(list, ...state.members.map((m) => {
    const notes = [AGE_LABELS[m.age_group], ...m.conditions.map((c) => COND_LABELS[c])].join(' · ');
    return h('li', { class: 'member' },
      h('span', { class: 'member-info' }, h('strong', { text: m.name }), h('small', { text: notes })),
      h('button', {
        type: 'button', class: 'btn btn-ghost btn-sm', 'aria-label': `Remove ${m.name}`, text: 'Remove',
        onclick: () => {
          state.members = state.members.filter((x) => x.id !== m.id);
          store.set('members', state.members);
          renderMembers();
          updateHouseholdSummary();
          renderFamilyAdvice();
          toast(`Removed ${m.name}`);
        },
      }));
  }));
}

function onMemberSubmit(e) {
  e.preventDefault();
  const f = e.currentTarget;
  const err = $('#member-error');
  const name = f.name.value.trim();
  if (!name) {
    err.textContent = 'Please enter a name or nickname.';
    f.name.focus();
    return;
  }
  if (state.members.length >= 10) {
    err.textContent = 'You can add up to 10 people.';
    return;
  }
  err.textContent = '';
  const member = {
    id: `m${Date.now().toString(36)}`,
    name: name.slice(0, 40),
    age_group: f.age_group.value,
    outdoor_time: f.outdoor_time.value,
    conditions: $$('input[name="conditions"]:checked', f).map((c) => c.value),
  };
  state.members.push(member);
  store.set('members', state.members);
  f.reset();
  renderMembers();
  updateHouseholdSummary();
  renderFamilyAdvice();
  f.name.focus();
  toast(`Added ${member.name}. Tap "Update advice" for tips.`);
}

// ---------- plan ----------

function restorePlanIfFresh() {
  if (state.plan) return;
  const saved = store.get('plan', null);
  if (saved && saved.key === locKey() && saved.date === todayStr()) {
    state.plan = saved.plan;
    renderPlan(saved.plan);
    $('#make-plan').textContent = '✨ Remake my plan';
  }
}

async function generatePlan() {
  if (!state.location) {
    toast('Choose your location first.');
    openCityDialog();
    return;
  }
  const btn = $('#make-plan');
  const famBtn = $('#refresh-family');
  [btn, famBtn].forEach((b) => { b.disabled = true; });
  btn.textContent = '✨ Making your plan…';
  const out = $('#plan-output');
  out.setAttribute('aria-busy', 'true');
  fill(out, h('div', { class: 'card' }, h('p', { class: 'muted', text: 'Reading the air and planning your day…' }), ...skeletonLines(5)));
  if (currentTab() === 'family') fill($('#family-advice'), ...skeletonLines(4));
  try {
    const plan = await api('/api/plan', {
      method: 'POST',
      body: {
        lat: state.location.lat,
        lon: state.location.lon,
        place_name: state.location.name,
        household: householdPayload(),
        language: state.lang,
      },
    });
    state.plan = plan;
    store.set('plan', { plan, key: locKey(), date: todayStr() });
    renderPlan(plan);
    renderFamilyAdvice();
  } catch (e) {
    fill(out, errorBlock(e.message, generatePlan));
    renderFamilyAdvice();
  } finally {
    [btn, famBtn].forEach((b) => { b.disabled = false; });
    btn.textContent = '✨ Remake my plan';
    out.removeAttribute('aria-busy');
  }
}

function impactBlock(imp) {
  const badges = [];
  if (imp.kind === 'exposure') {
    badges.push(h('span', { class: 'impact', role: 'listitem', text: `🫁 −${imp.exposure_cut_pct}% smog breathed` }));
    if (imp.cigarettes_avoided >= 0.05) {
      badges.push(h('span', { class: 'impact cig', role: 'listitem', text: `🚬 ${fmt(imp.cigarettes_avoided, 2)} cigarettes avoided` }));
    }
  } else if (imp.kind === 'emissions') {
    badges.push(h('span', { class: 'impact co2', role: 'listitem', text: `🌍 ${fmt(imp.co2_saved_year_kg)} kg CO₂ saved a year` }));
    badges.push(h('span', { class: 'impact', role: 'listitem', text: `−${imp.reduction_pct}% commute emissions` }));
  } else {
    badges.push(h('span', { class: 'impact info', role: 'listitem', text: `ℹ️ ${imp.label}` }));
  }
  const details = h('details', { class: 'math' },
    h('summary', { text: imp.kind === 'qualitative' ? 'Why this matters' : 'How we worked this out' }),
    imp.kind !== 'qualitative' ? h('p', { text: `Scenario: ${imp.label}.` }) : null,
    h('p', { text: imp.explanation }),
    imp.math ? h('code', { class: 'formula', text: imp.math }) : null);
  return [h('div', { class: 'impact-row', role: 'list', 'aria-label': 'Impact of this action' }, badges), details];
}

function actionItem(a) {
  return h('li', { class: 'action' },
    h('div', { class: 'action-time' },
      h('span', { class: 'cat-icon', 'aria-hidden': 'true', text: CATEGORY_ICONS[a.category] || '•' }),
      h('span', { text: `${TIME_ICONS[a.time] || ''} ${a.time}` })),
    h('div', {},
      h('h3', { text: a.title }),
      h('p', { text: a.detail }),
      h('p', { class: 'why' }, h('strong', { text: 'Why: ' }), a.why),
      a.impact ? impactBlock(a.impact) : null));
}

function checklistItems(items, prefix) {
  return items.map((c, i) => {
    const key = `${c.item}`.toLowerCase().slice(0, 80);
    const id = `${prefix}-check-${i}`;
    const box = h('input', { type: 'checkbox', id });
    box.checked = !!state.checks.done[key];
    box.addEventListener('change', () => {
      state.checks.done[key] = box.checked;
      store.set('checks', state.checks);
    });
    return h('li', {}, h('label', { for: id }, box, h('span', {}, c.item, h('span', { class: 'why', text: c.why }))));
  });
}

function renderPlan(plan) {
  const out = $('#plan-output');
  const parts = [];
  if (plan.notice) parts.push(h('p', { class: 'notice', role: 'note', text: `💡 ${plan.notice}` }));
  parts.push(h('article', { class: 'card plan-head' },
    h('h2', { class: 'h2', text: plan.headline }),
    h('p', { text: plan.summary }),
    h('p', { class: 'muted small', text: plan.mode === 'ai'
      ? `Made with Gemini from live air data · ${LANG_NAMES[state.lang]}`
      : 'Built-in SmogSafe tips from live air data' })));
  parts.push(h('article', { class: 'card' },
    h('h2', { class: 'h2', text: 'Your day, step by step' }),
    h('p', { class: 'muted small', text: 'Each step shows what it changes for you, and you can open the maths.' }),
    h('ol', { class: 'timeline' }, plan.actions.map(actionItem))));
  if (plan.swaps?.length) {
    parts.push(h('article', { class: 'card' },
      h('h2', { class: 'h2', text: '♻️ Sustainable swaps' }),
      h('ul', { class: 'swaps' }, plan.swaps.map((sw) => h('li', { class: 'swap' },
        h('p', { class: 'from', text: sw.swap_from }),
        h('p', { class: 'to', text: `→ ${sw.swap_to}` }),
        h('p', { class: 'why', text: sw.why }))))));
  }
  parts.push(h('article', { class: 'card' },
    h('h2', { class: 'h2', text: "🏠 Tonight's indoor-air checklist" }),
    h('ul', { class: 'checklist' }, checklistItems(plan.indoor_checklist, 'plan'))));
  fill(out, ...parts);
}

function renderFamilyAdvice() {
  const box = $('#family-advice');
  const plan = state.plan;
  fill($('#family-checklist'), ...checklistItems(plan?.indoor_checklist?.length ? plan.indoor_checklist : DEFAULT_CHECKLIST, 'fam'));
  if (!state.members.length) {
    fill(box, h('p', { class: 'muted empty' }, 'Add family members, then tap ', h('strong', { text: 'Update advice' }), '.'));
    return;
  }
  const advice = new Map((plan?.family || []).map((f) => [f.member_id, f]));
  const cards = state.members.map((m) => {
    const a = advice.get(m.id);
    return h('div', { class: 'advice-card' },
      h('h3', {}, h('span', { text: m.name }),
        h('small', { class: 'muted', text: AGE_LABELS[m.age_group] }),
        a ? h('span', { class: `risk risk-${a.risk_level}`, text: RISK_LABELS[a.risk_level] }) : null),
      a ? h('ul', {}, a.advice.map((t) => h('li', { text: t })))
        : h('p', { class: 'muted small', text: 'Tap "Update advice" to get tips for today.' }));
  });
  fill(box, ...cards);
}

// ---------- chat ----------

function inlineRich(text, byN) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|\[\d+\])/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith('**')) {
      out.push(h('strong', { text: tok.slice(2, -2) }));
    } else {
      const n = Number(tok.slice(1, -1));
      const src = byN.get(n);
      out.push(src
        ? h('sup', {}, h('a', { href: safeUrl(src.uri), target: '_blank', rel: 'noopener noreferrer', title: src.title, text: `[${n}]` }))
        : tok);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function renderRich(text, sources = []) {
  const frag = document.createDocumentFragment();
  const byN = new Map(sources.map((src) => [src.n, src]));
  let list = null;
  for (const raw of String(text).split('\n')) {
    const line = raw.trim().replace(/^#{1,6}\s+/, '');
    if (!line) {
      list = null;
      continue;
    }
    const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (bullet) {
      if (!list) {
        list = h('ul');
        frag.append(list);
      }
      list.append(h('li', {}, inlineRich(bullet[1], byN)));
    } else {
      list = null;
      frag.append(h('p', {}, inlineRich(line, byN)));
    }
  }
  return frag;
}

function searchChipsFrame(html) {
  const frame = h('iframe', {
    class: 'search-chips',
    title: 'Google Search suggestions',
    sandbox: 'allow-popups allow-popups-to-escape-sandbox',
    loading: 'lazy',
  });
  // Sandboxed with no scripts; links open in a new tab.
  frame.srcdoc = `<!doctype html><base target="_blank"><style>body{margin:0}</style>${html}`;
  return frame;
}

function sourcesList(sources) {
  if (!sources?.length) return null;
  return h('div', { class: 'sources' }, h('strong', { text: 'Sources' }),
    h('ol', {}, sources.map((src) => h('li', {},
      h('a', { href: safeUrl(src.uri), target: '_blank', rel: 'noopener noreferrer', text: src.title })))));
}

function appendMsg(kind, content) {
  const log = $('#chat-log');
  const msg = h('div', { class: `msg ${kind}` }, content);
  log.append(msg);
  log.scrollTop = log.scrollHeight;
  return msg;
}

async function askQuestion(question) {
  const q = question.trim();
  if (q.length < 2) return;
  if (!state.location) {
    toast('Choose your location first.');
    openCityDialog();
    return;
  }
  const input = $('#chat-input');
  const send = $('#chat-send');
  input.value = '';
  send.disabled = true;
  appendMsg('user', h('p', { text: q }));
  const typing = appendMsg('bot', h('span', { class: 'typing', 'aria-label': 'SmogSafe is typing' }, h('span'), h('span'), h('span')));
  try {
    const res = await api('/api/ask', {
      method: 'POST',
      body: {
        lat: state.location.lat,
        lon: state.location.lon,
        place_name: state.location.name,
        question: q,
        household: householdPayload(),
        history: state.chat.slice(-6),
        language: state.lang,
      },
    });
    typing.remove();
    appendMsg('bot', [
      renderRich(res.answer, res.sources),
      res.grounded === false ? h('p', { class: 'muted small', text: 'ℹ️ Answered without live Google Search, so it may miss very recent news.' }) : null,
      sourcesList(res.sources),
      res.suggestions_html ? searchChipsFrame(res.suggestions_html) : null,
    ]);
    state.chat.push({ role: 'user', text: q }, { role: 'model', text: res.answer.replace(/\[\d+\]/g, '').slice(0, 1900) });
  } catch (e) {
    typing.remove();
    appendMsg('bot error', h('p', { text: `⚠️ ${e.message}` }));
  } finally {
    send.disabled = false;
    input.focus();
  }
}

// ---------- calculators ----------

function barCompare(rows, unit) {
  const max = Math.max(...rows.map((r) => r.value), 0.0001);
  return h('div', { class: 'bar-compare' }, rows.map((r) => {
    const fill = h('div', { class: `bar-fill ${r.after ? 'after' : ''}` });
    fill.style.width = `${clamp((r.value / max) * 100, 2, 100)}%`;
    return h('div', { class: 'bar-line' },
      h('span', { text: r.label }),
      h('div', { class: 'bar-track', role: 'presentation' }, fill),
      h('span', { text: `${fmt(r.value, r.value < 10 ? 1 : 0)} ${unit}` }));
  }));
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
    const saves = r.co2_saved_year_kg >= 0;
    fill(box, 
      h('p', { class: 'big-stat', text: saves ? `${fmt(r.co2_saved_year_kg)} kg CO₂ saved a year` : `${fmt(-r.co2_saved_year_kg)} kg more CO₂ a year` }),
      h('p', { text: saves ? `That's ${r.reduction_pct}% less for this commute, about ${fmt(r.co2_saved_month_kg)} kg a month.` : 'This switch increases emissions.' }),
      barCompare([
        { label: MODE_LABELS[f.from_mode.value], value: r.co2_before_week_kg },
        { label: MODE_LABELS[f.to_mode.value], value: r.co2_after_week_kg, after: true },
      ], 'kg/wk'),
      saves ? h('p', {}, '🏙️ If 1,000 people in your city did this: ', h('strong', { text: `${fmt(r.if_1000_people_tonnes_year)} tonnes CO₂ a year` }), ', and fewer engines idling in the smog.') : null,
      h('details', { class: 'math' }, h('summary', { text: 'Show the maths' }), h('code', { class: 'formula', text: r.math })),
    );
  } catch (e) {
    fill(box, errorBlock(e.message));
  }
}, 250);

const runExposure = debounce(async () => {
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
    const better = r.exposure_cut_pct >= 0;
    fill(box, 
      h('p', { class: 'big-stat', text: better ? `${r.exposure_cut_pct}% less smog breathed` : `${-r.exposure_cut_pct}% more smog breathed` }),
      barCompare([
        { label: 'Before', value: r.dose_before_ug },
        { label: 'After', value: r.dose_after_ug, after: true },
      ], 'µg'),
      better && r.cigarettes_avoided > 0
        ? h('p', {}, '🚬 About ', h('strong', { text: `${fmt(r.cigarettes_avoided, 2)} cigarettes` }), ' of smoke avoided this session.')
        : null,
      h('details', { class: 'math' }, h('summary', { text: 'Show the maths' }), h('p', { text: r.explanation }), h('code', { class: 'formula', text: r.math })),
    );
  } catch (e) {
    fill(box, errorBlock(e.message));
  }
}, 250);

function initCalculators() {
  const options = (selected) => Object.entries(MODE_LABELS).map(([v, label]) => {
    const o = h('option', { value: v, text: label });
    if (v === selected) o.selected = true;
    return o;
  });
  const hhMode = state.household?.commute_mode;
  fill($('#c-from'), ...options(POLLUTING_MODES.includes(hhMode) ? hhMode : 'car_solo'));
  fill($('#c-to'), ...options('metro'));
  if (state.household?.commute_km) $('#c-km').value = clamp(Math.round(state.household.commute_km), 1, 50);
  $('#commute-calc').addEventListener('input', runCommute);
  $('#commute-calc').addEventListener('submit', (e) => e.preventDefault());
  $('#exposure-calc').addEventListener('input', runExposure);
  $('#exposure-calc').addEventListener('submit', (e) => e.preventDefault());
  runCommute();
  runExposure();
}

// ---------- Smog Circle ----------

async function loadCircle(force = false) {
  if (!state.location) return;
  const city = state.location.name;
  if (!force && state.communityFor === city) return;
  state.communityFor = city;
  fill($('#pledge-list'), ...skeletonLines(3));
  try {
    const data = await api(`/api/community?city=${encodeURIComponent(city)}&device_id=${encodeURIComponent(state.deviceId)}`);
    renderCircle(data);
  } catch (e) {
    state.communityFor = null;
    fill($('#pledge-list'), errorBlock(e.message, () => loadCircle(true)));
  }
}

function renderCircle(d) {
  fill($('#circle-counters'), 
    h('div', { class: 'counter' }, h('strong', { text: fmt(d.total_pledges) }), h('span', { class: 'muted', text: `${d.total_pledges === 1 ? 'pledge' : 'pledges'} in ${d.city}` })),
    h('div', { class: 'counter' }, h('strong', { text: `${fmt(d.people_pledging_co2_kg_year)} kg` }), h('span', { class: 'muted', text: 'CO₂ a year, if pledges are kept' })),
  );
  fill($('#pledge-list'), ...d.pledges.map((p) => {
    const btn = h('button', {
      type: 'button',
      class: 'btn btn-primary btn-sm',
      'aria-pressed': String(p.pledged_by_me),
      text: p.pledged_by_me ? 'Pledged ✓' : 'I pledge',
    });
    if (p.pledged_by_me) btn.disabled = true;
    btn.addEventListener('click', () => pledge(p.id, btn));
    return h('li', { class: 'pledge' },
      h('span', { class: 'pledge-icon', 'aria-hidden': 'true', text: p.icon }),
      h('div', {},
        h('h3', { text: p.title }),
        h('p', { text: `${fmt(p.count)} ${p.count === 1 ? 'person' : 'people'}${p.yearly_co2_kg ? ` · ~${fmt(p.yearly_co2_kg)} kg CO₂/yr each` : ''}` }),
        h('p', { text: p.note })),
      btn);
  }));
}

async function pledge(id, btn) {
  btn.disabled = true;
  try {
    const data = await api('/api/community/pledge', {
      method: 'POST',
      body: { city: state.location.name, pledge_id: id, device_id: state.deviceId },
    });
    renderCircle(data);
    toast(data.added ? 'Thank you for pledging! 💚' : 'You have already made this pledge.');
  } catch (e) {
    toast(e.message);
    btn.disabled = false;
  }
}

async function loadAdvisories(force = false) {
  if (!state.location) return;
  const key = `${state.location.name}|${state.location.state || ''}`;
  if (!force && state.advisoriesFor === key) return;
  state.advisoriesFor = key;
  const box = $('#advisories');
  const btn = $('#refresh-advisories');
  btn.disabled = true;
  fill(box, h('p', { class: 'muted small', text: 'Searching for the latest advisories…' }), ...skeletonLines(3));
  try {
    const params = new URLSearchParams({ city: state.location.name, state: state.location.state || '' });
    const d = await api(`/api/advisories?${params}`);
    fill(box, 
      h('ul', { class: 'advisory-list' }, d.items.map((t) => h('li', {}, inlineRich(t, new Map())))),
      sourcesList(d.sources),
      d.suggestions_html ? searchChipsFrame(d.suggestions_html) : null,
    );
  } catch (e) {
    state.advisoriesFor = null;
    fill(box, errorBlock(e.message, () => loadAdvisories(true)));
  } finally {
    btn.disabled = false;
  }
}

// ---------- "How we calculate" ----------

function factorTable(caption, rows, headers) {
  return h('table', { class: 'factor-table' },
    h('caption', { class: 'sr-only', text: caption }),
    h('thead', {}, h('tr', {}, headers.map((t) => h('th', { scope: 'col', text: t })))),
    h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c) => h('td', { text: c }))))));
}

async function openFactors() {
  const dlg = $('#factors-dialog');
  if (typeof dlg.showModal === 'function') dlg.showModal();
  if (state.factors) return;
  const body = $('#factors-body');
  try {
    const f = await api('/api/impact/factors');
    state.factors = f;
    fill(body, 
      h('p', {}, h('strong', { text: 'Cigarette rule: ' }),
        `breathing ${f.cigarette_pm25_ugm3} µg/m³ of PM2.5 for a day is roughly as harmful as one cigarette. An adult breathes about ${f.daily_air_m3} m³ of air a day, so one cigarette ≈ ${fmt(f.ug_per_cigarette)} µg of PM2.5 inhaled.`),
      h('p', {}, h('strong', { text: 'Smog breathed' }), ' = PM2.5 outside × share that reaches you (setting × mask) × breathing rate × time.'),
      h('h3', { class: 'h3', text: 'Breathing rate (m³ per hour)' }),
      factorTable('Breathing rates', Object.entries(f.breathing_m3_per_hour).map(([k, v]) => [k, v]), ['Activity', 'm³/hour']),
      h('h3', { class: 'h3', text: 'Share of outdoor PM2.5 reaching you' }),
      factorTable('Setting factors', Object.entries(f.setting_factor).map(([k, v]) => [f.setting_labels[k], v]), ['Setting', 'Share']),
      factorTable('Mask factors', Object.entries(f.mask_factor).map(([k, v]) => [f.mask_labels[k], v]), ['Mask', 'Share that gets through']),
      h('h3', { class: 'h3', text: 'Commute emissions (kg CO₂ per passenger-km)' }),
      factorTable('Commute emissions', Object.entries(f.co2_kg_per_pkm).map(([k, v]) => [f.mode_labels[k], v]), ['Mode', 'kg CO₂/km']),
      h('p', { class: 'muted small', text: 'All values are rounded estimates meant to compare choices, not exact measurements.' }),
      h('h3', { class: 'h3', text: 'Sources' }),
      h('ul', {}, f.sources.map((src) => h('li', {}, h('a', { href: safeUrl(src.url), target: '_blank', rel: 'noopener noreferrer', text: src.label })))),
    );
  } catch (e) {
    fill(body, errorBlock(e.message));
  }
}

// ---------- init ----------

function init() {
  initTabs();
  applyLocationUI();

  $('#lang-select').value = state.lang;
  $('#lang-select').addEventListener('change', (e) => {
    state.lang = e.target.value;
    store.set('lang', state.lang);
    toast(`AI plans and answers will be in ${LANG_NAMES[state.lang]}.`);
  });

  if (state.household) fillHousehold(state.household);
  else $('#household-details').open = true;
  $('#household-form').addEventListener('submit', (e) => {
    e.preventDefault();
    state.household = readHousehold();
    store.set('household', state.household);
    updateHouseholdSummary();
    $('#household-details').open = false;
    generatePlan();
  });
  $('#make-plan').addEventListener('click', () => {
    if (!state.household) {
      state.household = readHousehold();
      store.set('household', state.household);
      updateHouseholdSummary();
    }
    generatePlan();
  });
  $('#refresh-family').addEventListener('click', generatePlan);
  $('#member-form').addEventListener('submit', onMemberSubmit);
  renderMembers();
  updateHouseholdSummary();
  renderFamilyAdvice();

  $('#location-btn').addEventListener('click', openCityDialog);
  $('#use-location').addEventListener('click', () => detectLocation());
  $('#search-city').addEventListener('click', openCityDialog);
  $('#dialog-use-location').addEventListener('click', () => {
    $('#city-dialog').close();
    detectLocation();
  });
  $('#city-input').addEventListener('input', (e) => searchCities(e.target.value));
  $('#open-factors').addEventListener('click', openFactors);

  $('#chat-form').addEventListener('submit', (e) => {
    e.preventDefault();
    askQuestion($('#chat-input').value);
  });
  $$('#chat-suggestions .chip').forEach((chip) => chip.addEventListener('click', () => askQuestion(chip.textContent)));
  $('#refresh-advisories').addEventListener('click', () => loadAdvisories(true));

  initCalculators();
  window.addEventListener('resize', debounce(() => state.air && renderChart(state.air), 200));

  if (state.location) loadAir();
  else detectLocation({ silent: true });
}

init();
