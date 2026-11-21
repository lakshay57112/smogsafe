// Today's plan, per-person family advice and the indoor-air checklist.

import { api } from './api.js';
import {
  AGE_LABELS, CATEGORY_ICONS, DEFAULT_CHECKLIST, LANG_CODES, LANG_NAMES, RISK_LABELS, TIME_ICONS,
} from './constants.js';
import { $, badge, errorBlock, fill, h, icon, skeletonLines, toast } from './dom.js';
import { householdPayload } from './household.js';
import { openCityDialog } from './location.js';
import { locKey, state, store } from './store.js';
import { currentTab } from './tabs.js';
import { fmt, todayStr } from './utils.js';

const setPlanLabel = (text) => { $('#make-plan-label').textContent = text; };

/** Show today's saved plan for this location without calling the API again. */
export function restorePlanIfFresh() {
  if (state.plan) return;
  const saved = store.get('plan', null);
  if (saved && saved.key === locKey() && saved.date === todayStr()) {
    state.plan = saved.plan;
    renderPlan(saved.plan);
    setPlanLabel('Remake my plan');
  }
}

function setPlanBusy(busy) {
  [$('#make-plan'), $('#refresh-family')].forEach((b) => { b.disabled = busy; });
  setPlanLabel(busy ? 'Making your plan…' : 'Remake my plan');
  const out = $('#plan-output');
  if (busy) out.setAttribute('aria-busy', 'true');
  else out.removeAttribute('aria-busy');
}

export async function generatePlan() {
  if (!state.location) {
    toast('Choose your location first.');
    openCityDialog();
    return;
  }
  setPlanBusy(true);
  const out = $('#plan-output');
  fill(out, h('div', { class: 'card' }, h('p', { class: 'muted', text: 'Reading the air and planning your day…' }), skeletonLines(5)));
  if (currentTab() === 'family') fill($('#family-advice'), skeletonLines(4));
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
    renderPlan(plan, { focus: currentTab() === 'plan' });
    renderFamilyAdvice();
  } catch (e) {
    fill(out, errorBlock(e.message, generatePlan));
    renderFamilyAdvice();
  } finally {
    setPlanBusy(false);
  }
}

function impactBadges(imp) {
  if (imp.kind === 'exposure') {
    return [
      badge('impact', '🫁', `−${imp.exposure_cut_pct}% smog breathed`),
      imp.cigarettes_avoided >= 0.05 ? badge('impact cig', '🚬', `${fmt(imp.cigarettes_avoided, 2)} cigarettes avoided`) : null,
    ];
  }
  if (imp.kind === 'emissions') {
    return [
      badge('impact co2', '🌍', `${fmt(imp.co2_saved_year_kg)} kg CO₂ saved a year`),
      h('span', { class: 'impact', role: 'listitem', text: `−${imp.reduction_pct}% commute emissions` }),
    ];
  }
  return [badge('impact info', 'ℹ️', imp.label)];
}

/** Impact badges plus an expandable "how we worked this out" with the formula. */
function impactBlock(imp) {
  const qualitative = imp.kind === 'qualitative';
  return [
    h('div', { class: 'impact-row', role: 'list', 'aria-label': 'Impact of this action' }, impactBadges(imp)),
    h('details', { class: 'math' },
      h('summary', { text: qualitative ? 'Why this matters' : 'How we worked this out' }),
      qualitative ? null : h('p', { text: `Scenario: ${imp.label}.` }),
      h('p', { text: imp.explanation }),
      imp.math ? h('code', { class: 'formula', text: imp.math }) : null),
  ];
}

function actionItem(a) {
  return h('li', { class: 'action' },
    h('div', { class: 'action-time' },
      h('span', { class: 'cat-icon', 'aria-hidden': 'true', text: CATEGORY_ICONS[a.category] || '•' }),
      h('span', {}, icon(TIME_ICONS[a.time] || ''), a.time)),
    h('div', {},
      h('h3', { text: a.title }),
      h('p', { text: a.detail }),
      h('p', { class: 'why' }, h('strong', { text: 'Why: ' }), a.why),
      a.impact ? impactBlock(a.impact) : null));
}

/** Checkboxes whose ticks are remembered for the day. */
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

function renderPlan(plan, { focus = false } = {}) {
  const out = $('#plan-output');
  const headline = h('h2', { class: 'h2', tabindex: '-1', text: plan.headline });
  const madeWith = plan.mode === 'ai'
    ? `Made with Gemini from live air data · ${LANG_NAMES[state.lang]}`
    : 'Built-in SmogSafe tips from live air data';
  out.lang = plan.mode === 'ai' ? LANG_CODES[state.lang] : 'en';
  fill(out,
    plan.notice ? h('p', { class: 'notice', role: 'note' }, icon('💡'), plan.notice) : null,
    h('article', { class: 'card plan-head' }, headline, h('p', { text: plan.summary }), h('p', { class: 'muted small', text: madeWith })),
    h('article', { class: 'card' },
      h('h2', { class: 'h2', text: 'Your day, step by step' }),
      h('p', { class: 'muted small', text: 'Each step shows what it changes for you, and you can open the maths.' }),
      h('ol', { class: 'timeline' }, plan.actions.map(actionItem))),
    plan.swaps?.length
      ? h('article', { class: 'card' },
        h('h2', { class: 'h2' }, icon('♻️'), 'Sustainable swaps'),
        h('ul', { class: 'swaps' }, plan.swaps.map((sw) => h('li', { class: 'swap' },
          h('p', { class: 'from', text: sw.swap_from }),
          h('p', { class: 'to', text: `→ ${sw.swap_to}` }),
          h('p', { class: 'why', text: sw.why })))))
      : null,
    h('article', { class: 'card' },
      h('h2', { class: 'h2' }, icon('🏠'), "Tonight's indoor-air checklist"),
      h('ul', { class: 'checklist' }, checklistItems(plan.indoor_checklist, 'plan'))));
  // Move focus to the new plan so keyboard and screen-reader users land on it.
  if (focus) headline.focus();
}

function adviceCard(member, advice) {
  return h('div', { class: 'advice-card' },
    h('h3', {}, h('span', { text: member.name }),
      h('small', { class: 'muted', text: AGE_LABELS[member.age_group] }),
      advice ? h('span', { class: `risk risk-${advice.risk_level}`, text: RISK_LABELS[advice.risk_level] }) : null),
    advice
      ? h('ul', {}, advice.advice.map((t) => h('li', { text: t })))
      : h('p', { class: 'muted small', text: 'Tap "Update advice" to get tips for today.' }));
}

export function renderFamilyAdvice() {
  const plan = state.plan;
  const checklist = plan?.indoor_checklist?.length ? plan.indoor_checklist : DEFAULT_CHECKLIST;
  fill($('#family-checklist'), checklistItems(checklist, 'fam'));
  const box = $('#family-advice');
  if (!state.members.length) {
    fill(box, h('p', { class: 'muted empty' }, 'Add family members, then tap ', h('strong', { text: 'Update advice' }), '.'));
    return;
  }
  const advice = new Map((plan?.family || []).map((f) => [f.member_id, f]));
  box.lang = plan?.mode === 'ai' ? LANG_CODES[state.lang] : 'en';
  fill(box, state.members.map((m) => adviceCard(m, advice.get(m.id))));
}
