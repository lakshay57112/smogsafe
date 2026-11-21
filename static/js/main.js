// SmogSafe frontend entry point: wires up events and loads the first screen.
// Plain ES modules, no framework or build step.

import { loadAir, renderChart } from './air.js';
import { initCalculators } from './calculators.js';
import { askQuestion } from './chat.js';
import { loadAdvisories } from './circle.js';
import { LANG_NAMES } from './constants.js';
import { $, $$, toast } from './dom.js';
import { openFactors } from './factors.js';
import { fillHousehold, onMemberSubmit, renderMembers, saveHousehold, updateHouseholdSummary } from './household.js';
import { applyLocationUI, detectLocation, openCityDialog, searchCities } from './location.js';
import { generatePlan, renderFamilyAdvice } from './plan.js';
import { state, store } from './store.js';
import { initTabs } from './tabs.js';
import { debounce } from './utils.js';

function initLanguage() {
  const select = $('#lang-select');
  select.value = state.lang;
  select.addEventListener('change', () => {
    state.lang = select.value;
    store.set('lang', state.lang);
    toast(`AI plans and answers will be in ${LANG_NAMES[state.lang]}.`);
  });
}

function initHousehold() {
  if (state.household) fillHousehold(state.household);
  else $('#household-details').open = true;
  $('#household-form').addEventListener('submit', (e) => {
    e.preventDefault();
    saveHousehold();
    $('#household-details').open = false;
    generatePlan();
  });
  $('#make-plan').addEventListener('click', () => {
    if (!state.household) saveHousehold();
    generatePlan();
  });
  $('#refresh-family').addEventListener('click', generatePlan);
  $('#member-form').addEventListener('submit', onMemberSubmit);
  renderMembers();
  updateHouseholdSummary();
  renderFamilyAdvice();
}

function initLocation() {
  applyLocationUI();
  $('#location-btn').addEventListener('click', openCityDialog);
  $('#use-location').addEventListener('click', () => detectLocation());
  $('#search-city').addEventListener('click', openCityDialog);
  $('#dialog-use-location').addEventListener('click', () => {
    $('#city-dialog').close();
    detectLocation();
  });
  $('#city-input').addEventListener('input', (e) => searchCities(e.target.value));
}

function initChat() {
  $('#chat-form').addEventListener('submit', (e) => {
    e.preventDefault();
    askQuestion($('#chat-input').value);
  });
  $$('#chat-suggestions .chip').forEach((chip) => chip.addEventListener('click', () => askQuestion(chip.textContent)));
}

function init() {
  initTabs();
  initLanguage();
  initHousehold();
  initLocation();
  initChat();
  initCalculators();
  $('#open-factors').addEventListener('click', openFactors);
  $('#refresh-advisories').addEventListener('click', () => loadAdvisories(true));
  window.addEventListener('resize', debounce(() => state.air && renderChart(state.air), 200));

  if (state.location) loadAir();
  else detectLocation({ silent: true });
}

init();
