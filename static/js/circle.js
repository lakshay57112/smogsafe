// Smog Circle: anonymous city pledges and live local advisories.

import { api } from './api.js';
import { $, errorBlock, fill, h, skeletonLines, toast } from './dom.js';
import { renderInline, searchFrame, sourcesList } from './rich.js';
import { state } from './store.js';
import { fmt, plural } from './utils.js';

export async function loadCircle(force = false) {
  if (!state.location) return;
  const city = state.location.name;
  if (!force && state.communityFor === city) return;
  state.communityFor = city;
  fill($('#pledge-list'), skeletonLines(3));
  try {
    const params = new URLSearchParams({ city, device_id: state.deviceId });
    renderCircle(await api(`/api/community?${params}`));
  } catch (e) {
    state.communityFor = null;
    fill($('#pledge-list'), errorBlock(e.message, () => loadCircle(true)));
  }
}

function counter(value, label) {
  return h('div', { class: 'counter' }, h('strong', { text: value }), h('span', { class: 'muted', text: label }));
}

function pledgeItem(p) {
  const titleId = `pledge-title-${p.id}`;
  const btn = h('button', {
    type: 'button',
    class: 'btn btn-primary btn-sm',
    'aria-pressed': String(p.pledged_by_me),
    'aria-describedby': titleId,
    text: p.pledged_by_me ? 'Pledged ✓' : 'I pledge',
  });
  btn.disabled = p.pledged_by_me;
  btn.addEventListener('click', () => pledge(p.id, btn));
  const perHousehold = p.yearly_co2_kg ? ` · ~${fmt(p.yearly_co2_kg)} kg CO₂/yr each` : '';
  return h('li', { class: 'pledge' },
    h('span', { class: 'pledge-icon', 'aria-hidden': 'true', text: p.icon }),
    h('div', {},
      h('h3', { id: titleId, text: p.title }),
      h('p', { text: `${fmt(p.count)} ${plural(p.count, 'person', 'people')}${perHousehold}` }),
      h('p', { text: p.note })),
    btn);
}

function renderCircle(d) {
  fill($('#circle-counters'),
    counter(fmt(d.total_pledges), `${plural(d.total_pledges, 'pledge', 'pledges')} in ${d.city}`),
    counter(`${fmt(d.people_pledging_co2_kg_year)} kg`, 'CO₂ a year, if pledges are kept'));
  fill($('#pledge-list'), d.pledges.map(pledgeItem));
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

export async function loadAdvisories(force = false) {
  if (!state.location) return;
  const key = `${state.location.name}|${state.location.state || ''}`;
  if (!force && state.advisoriesFor === key) return;
  state.advisoriesFor = key;
  const box = $('#advisories');
  const btn = $('#refresh-advisories');
  btn.disabled = true;
  fill(box, h('p', { class: 'muted small', text: 'Searching for the latest advisories…' }), skeletonLines(3));
  try {
    const params = new URLSearchParams({ city: state.location.name, state: state.location.state || '' });
    const d = await api(`/api/advisories?${params}`);
    fill(box,
      h('ul', { class: 'advisory-list' }, d.items.map((t) => h('li', {}, renderInline(t)))),
      sourcesList(d.sources),
      searchFrame(d.suggestions_url));
  } catch (e) {
    state.advisoriesFor = null;
    fill(box, errorBlock(e.message, () => loadAdvisories(true)));
  } finally {
    btn.disabled = false;
  }
}
