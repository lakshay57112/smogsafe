// Accessible tabs: click, arrow keys, Home/End (WAI-ARIA tabs pattern).

import { loadAdvisories, loadCircle } from './circle.js';
import { $, $$ } from './dom.js';
import { renderFamilyAdvice } from './plan.js';

const allTabs = () => $$('[role="tab"]');

export const currentTab = () =>
  (allTabs().find((t) => t.getAttribute('aria-selected') === 'true')?.id || 'tab-plan').replace('tab-', '');

function onTabShown(name) {
  if (name === 'family') renderFamilyAdvice();
  if (name === 'circle') {
    loadCircle();
    loadAdvisories();
  }
}

export function selectTab(tab, focus = false) {
  allTabs().forEach((t) => {
    const selected = t === tab;
    t.setAttribute('aria-selected', String(selected));
    t.tabIndex = selected ? 0 : -1;
    $(`#${t.getAttribute('aria-controls')}`).hidden = !selected;
  });
  if (focus) tab.focus();
  onTabShown(tab.id.replace('tab-', ''));
}

const KEY_STEPS = { ArrowRight: 1, ArrowLeft: -1 };

export function initTabs() {
  const list = allTabs();
  list.forEach((tab, i) => {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('keydown', (e) => {
      let j = null;
      if (e.key in KEY_STEPS) j = (i + KEY_STEPS[e.key] + list.length) % list.length;
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
