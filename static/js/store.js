// App state, persisted to localStorage. Nothing personal is sent to the server except per request.

import { todayStr } from './utils.js';

export const store = {
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

function newDeviceId() {
  const raw = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const id = raw.replace(/[^A-Za-z0-9-]/g, '').slice(0, 60);
  store.set('device', id);
  return id;
}

export const state = {
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

// Checklist ticks reset every day.
if (state.checks.date !== todayStr()) state.checks = { date: todayStr(), done: {} };

/** Location key rounded to ~1 km, used to decide if a saved plan still applies. */
export const locKey = () =>
  (state.location ? `${state.location.lat.toFixed(2)},${state.location.lon.toFixed(2)}` : '');
