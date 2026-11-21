// Household profile (commute, cooking, purifier...) and family members. Stored only in this browser.

import { AGE_LABELS, COND_LABELS, MODE_LABELS } from './constants.js';
import { $, $$, fill, h, toast } from './dom.js';
import { renderFamilyAdvice } from './plan.js';
import { state, store } from './store.js';
import { clamp, plural } from './utils.js';

const MAX_MEMBERS = 10;

export function readHousehold() {
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

export function fillHousehold(hh) {
  const f = $('#household-form');
  f.commute_mode.value = hh.commute_mode;
  f.commute_km.value = hh.commute_km;
  f.commute_days.value = hh.commute_days;
  f.cooking_fuel.value = hh.cooking_fuel;
  f.has_purifier.checked = !!hh.has_purifier;
  f.near_busy_road.checked = !!hh.near_busy_road;
  f.exercises_outdoors.checked = !!hh.exercises_outdoors;
}

export function saveHousehold() {
  state.household = readHousehold();
  store.set('household', state.household);
  updateHouseholdSummary();
}

/** What the plan and chat endpoints receive. */
export const householdPayload = () => ({ ...(state.household || readHousehold()), members: state.members });

export function updateHouseholdSummary() {
  const hh = state.household;
  const n = state.members.length;
  $('#household-summary').textContent = hh
    ? [
      MODE_LABELS[hh.commute_mode],
      hh.commute_km ? `${hh.commute_km} km` : null,
      `${n} family ${plural(n, 'member', 'members')}`,
      hh.has_purifier ? 'purifier' : null,
    ].filter(Boolean).join(' · ')
    : 'Tell us a little so tips fit your life';
}

function saveMembers() {
  store.set('members', state.members);
  renderMembers();
  updateHouseholdSummary();
  renderFamilyAdvice();
}

export function renderMembers() {
  const list = $('#member-list');
  if (!state.members.length) {
    fill(list, h('li', { class: 'muted', text: 'No one added yet.' }));
    return;
  }
  fill(list, state.members.map((m) => {
    const notes = [AGE_LABELS[m.age_group], ...m.conditions.map((c) => COND_LABELS[c])].join(' · ');
    return h('li', { class: 'member' },
      h('span', { class: 'member-info' }, h('strong', { text: m.name }), h('small', { text: notes })),
      h('button', {
        type: 'button',
        class: 'btn btn-ghost btn-sm',
        'aria-label': `Remove ${m.name}`,
        text: 'Remove',
        onclick: () => {
          state.members = state.members.filter((x) => x.id !== m.id);
          saveMembers();
          toast(`Removed ${m.name}`);
        },
      }));
  }));
}

function showMemberError(form, message) {
  const err = $('#member-error');
  err.textContent = message;
  form.name.setAttribute('aria-invalid', message ? 'true' : 'false');
  if (message) form.name.focus();
}

export function onMemberSubmit(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const name = form.name.value.trim();
  const problem = !name ? 'Please enter a name or nickname.'
    : state.members.length >= MAX_MEMBERS ? `You can add up to ${MAX_MEMBERS} people.` : '';
  showMemberError(form, problem);
  if (problem) return;
  const member = {
    id: `m${Date.now().toString(36)}`,
    name: name.slice(0, 40),
    age_group: form.age_group.value,
    outdoor_time: form.outdoor_time.value,
    conditions: $$('input[name="conditions"]:checked', form).map((c) => c.value),
  };
  state.members.push(member);
  form.reset();
  saveMembers();
  form.name.focus();
  toast(`Added ${member.name}. Tap "Update advice" for tips.`);
}
