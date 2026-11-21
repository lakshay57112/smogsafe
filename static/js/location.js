// Where the user is: auto-detect, city search dialog, and switching location.

import { loadAir } from './air.js';
import { api } from './api.js';
import { loadAdvisories, loadCircle } from './circle.js';
import { DEFAULT_LOCATION } from './constants.js';
import { $, fill, h, skeletonLines, toast } from './dom.js';
import { state, store } from './store.js';
import { currentTab } from './tabs.js';
import { debounce } from './utils.js';

export function applyLocationUI() {
  const name = state.location?.name || 'your area';
  $('#location-name').textContent = state.location ? name : 'Find my air';
  $('#air-place').textContent = name;
  $('#circle-city').textContent = name;
}

export function setLocation(loc) {
  state.location = loc;
  store.set('location', loc);
  state.plan = null;
  state.chat = [];
  applyLocationUI();
  fill($('#plan-output'));
  loadAir();
  if (currentTab() === 'circle') {
    loadCircle(true);
    loadAdvisories(true);
  }
}

export function openCityDialog() {
  const dlg = $('#city-dialog');
  if (typeof dlg.showModal === 'function' && !dlg.open) dlg.showModal();
  $('#city-input').focus();
}

/** Use the browser's location. `silent` falls back to New Delhi instead of opening the search dialog. */
export function detectLocation({ silent = false } = {}) {
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

function cityButton(r) {
  const region = r.district && r.district !== r.name ? `${r.district}, ${r.state}` : r.state;
  return h('li', {},
    h('button', {
      type: 'button',
      onclick: () => {
        $('#city-dialog').close();
        setLocation({ lat: r.lat, lon: r.lon, name: r.name, state: r.state });
      },
    }, h('strong', { text: r.name }), region ? ` · ${region}` : ''));
}

export const searchCities = debounce(async (query) => {
  const list = $('#city-results');
  const q = query.trim();
  if (q.length < 2) {
    fill(list);
    return;
  }
  fill(list, h('li', { class: 'muted', text: 'Searching…' }));
  try {
    const { results } = await api(`/api/geocode/search?q=${encodeURIComponent(q)}`, { timeout: 10000 });
    fill(list, results.length
      ? results.map(cityButton)
      : h('li', { class: 'muted', text: 'No Indian city found with that name.' }));
  } catch (e) {
    fill(list, h('li', { class: 'form-error', text: e.message }));
  }
}, 300);
