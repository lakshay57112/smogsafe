// "Ask SmogSafe" chat: grounded Gemini answers with citations and sources.

import { api } from './api.js';
import { LANG_CODES } from './constants.js';
import { $, h, toast } from './dom.js';
import { householdPayload } from './household.js';
import { openCityDialog } from './location.js';
import { renderRich, searchFrame, sourcesList } from './rich.js';
import { state } from './store.js';
import { stripCitations } from './utils.js';

const HISTORY_TURNS = 6;

function appendMsg(kind, content) {
  const log = $('#chat-log');
  const msg = h('div', { class: `msg ${kind}` }, content);
  log.append(msg);
  log.scrollTop = log.scrollHeight;
  return msg;
}

function answerBubble(res) {
  const msg = appendMsg('bot', [
    renderRich(res.answer, res.sources),
    res.grounded === false
      ? h('p', { class: 'muted small', text: 'ℹ️ Answered without live Google Search, so it may miss very recent news.' })
      : null,
    sourcesList(res.sources),
    searchFrame(res.suggestions_url),
  ]);
  if (res.mode === 'ai') msg.lang = LANG_CODES[state.lang];
  return msg;
}

export async function askQuestion(question) {
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
  const typing = appendMsg('bot',
    h('span', { class: 'typing', role: 'status', 'aria-label': 'SmogSafe is typing' }, h('span'), h('span'), h('span')));
  try {
    const res = await api('/api/ask', {
      method: 'POST',
      body: {
        lat: state.location.lat,
        lon: state.location.lon,
        place_name: state.location.name,
        question: q,
        household: householdPayload(),
        history: state.chat.slice(-HISTORY_TURNS),
        language: state.lang,
      },
    });
    typing.remove();
    answerBubble(res);
    state.chat.push({ role: 'user', text: q }, { role: 'model', text: stripCitations(res.answer).slice(0, 1900) });
  } catch (e) {
    typing.remove();
    appendMsg('bot error', h('p', { text: `⚠️ ${e.message}` }));
  } finally {
    send.disabled = false;
    input.focus();
  }
}
