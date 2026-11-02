// AI 教练抽屉：意图 chips + SSE 流式构筑 / 换卡 / 点评 + 采纳到组卡器
import { get, post, stream, toast } from './api.js';
import { currentDeck, deckContext, getSelected } from './cards.js';

const state = {
  intent: '',
  lastDeckCode: '',
  busy: false,
  es: null,
};

function escapeHtml(s) {
  // 用数字实体，避免源码里出现 & 字面量与模板字符串冲突
  return String(s ?? '').replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';');
}

function out() { return document.getElementById('aiOut'); }

function clearOut() { const o = out(); if (o) o.textContent = ''; }

function append(kind, text) {
  const o = out();
  if (!o) return;
  const span = document.createElement(kind === 'status' ? 'div' : 'span');
  if (kind === 'status') {
    span.style.cssText = 'color:var(--text-faint);font-size:12px';
    span.textContent = '· ' + text;
  } else {
    span.textContent = text;
  }
  o.appendChild(span);
  o.scrollTop = o.scrollHeight;
}

function setBusy(busy) {
  state.busy = busy;
  ['btnBuild', 'btnSwap', 'btnReview'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = busy;
  });
}

// 当前卡组 -> 卡组码（供 AI 侧解析）
async function currentDeckCode() {
  const items = currentDeck();
  if (!items.length) return '';
  const ctx = deckContext();
  try {
    const d = await post('/decks/encode', {
      card_class: ctx.card_class,
      mode: ctx.mode,
      fmt: ctx.mode === 'wild' ? 'wild' : 'standard',
      cards: items.map(c => ({ dbf_id: c.dbf_id, qty: c.qty })),
    });
    return d.deck_code || '';
  } catch {
    return '';
  }
}

function runStream(kind, params, onResult) {
  if (state.busy) { toast('正在生成中…'); return; }
  setBusy(true);
  clearOut();
  state.es = stream('/ai/' + kind, params, {
    onDelta: t => append('text', t),
    onStatus: t => append('status', t),
    onDone: d => {
      setBusy(false);
      onResult && onResult(d);
    },
    onError: m => { setBusy(false); append('status', '失败：' + m); },
  });
}

async function doBuild() {
  const ctx = deckContext();
  const note = (document.getElementById('intentText').value || '').trim();
  runStream('build', {
    card_class: ctx.card_class,
    mode: ctx.mode,
    intent: state.intent,
    note,
  }, d => {
    if (!d || d.type !== 'result') return;
    if (d.llm_error) append('status', '模型不可用：' + d.llm_error);
    if (d.ok) {
      state.lastDeckCode = d.deck_code || '';
      const btn = document.getElementById('btnApplyDeck');
      if (btn) btn.disabled = !state.lastDeckCode;
      append('status', `来源：${d.source === 'rules' ? '规则兜底' : '模型 ' + (d.model || '')}`
        + `｜候选 ${d.candidates} 张｜尝试 ${d.attempts} 次｜张数 ${d.total}｜尘 ${(d.analysis || {}).dust_total || 0}`);
      append('text', `\n卡组码 ${state.lastDeckCode}\n`);
      toast('构筑完成，点「采纳这套卡组」导入');
    } else {
      append('status', '未生成可用卡组：' + (d.errors || []).join('；'));
    }
  });
}

async function doSwap() {
  const target = getSelected();
  if (!target) { toast('先在组卡器里点一张卡组中的卡作为换卡对象'); return; }
  const code = await currentDeckCode();
  if (!code) { toast('当前卡组为空或编码失败'); return; }
  const ctx = deckContext();
  const note = (document.getElementById('intentText').value || '').trim();
  runStream('swap', {
    card_class: ctx.card_class,
    mode: ctx.mode,
    deck_code: code,
    target: target.name,
    intent: state.intent,
    note,
  }, d => {
    if (!d || d.type !== 'result') return;
    if (d.swaps && d.swaps.length) {
      const first = d.swaps[0];
      state.lastDeckCode = first.deck_code || state.lastDeckCode;
      const btn = document.getElementById('btnApplyDeck');
      if (btn) btn.disabled = !state.lastDeckCode;
      append('status', `来源：${d.source === 'rules' ? '规则兜底' : '模型'}｜「采纳」会导入采用首条替换后的卡组`);
    }
  });
}

async function doReview() {
  const code = await currentDeckCode();
  if (!code) { toast('当前卡组为空或编码失败'); return; }
  const ctx = deckContext();
  runStream('review', { card_class: ctx.card_class, mode: ctx.mode, deck_code: code });
}

function applyDeck() {
  if (!state.lastDeckCode) { toast('还没有可采纳的卡组'); return; }
  const input = document.getElementById('deckCodeInput');
  if (input) {
    input.value = state.lastDeckCode;
    document.getElementById('btnImportCode').click();
    document.getElementById('btnCloseDrawer').click();
    document.querySelector('[data-view="viewBuilder"]').click();
  }
}

async function loadIntents() {
  let d;
  try {
    d = await get('/ai/status');
  } catch { return; }
  const box = document.getElementById('intentChips');
  if (!box) return;
  const items = (d.intents || []);
  box.innerHTML = items.map(i => `<button class="chip" data-intent="${i.id}">${escapeHtml(i.label)}</button>`).join('');
  box.addEventListener('click', e => {
    const b = e.target.closest('[data-intent]');
    if (!b) return;
    const id = b.dataset.intent;
    state.intent = state.intent === id ? '' : id;
    // 主题里 chip 的选中态用的是 aria-pressed
    box.querySelectorAll('.chip').forEach(c => {
      const on = c.dataset.intent === state.intent;
      c.classList.toggle('active', on);
      c.setAttribute('aria-pressed', String(on));
    });
  });
  if (!d.configured) append('status', '未配置 LLM 网关，AI 功能将走规则兜底');
}

export function initAi() {
  const b = document.getElementById('btnBuild');
  const s = document.getElementById('btnSwap');
  const r = document.getElementById('btnReview');
  const a = document.getElementById('btnApplyDeck');
  if (b) b.addEventListener('click', doBuild);
  if (s) s.addEventListener('click', doSwap);
  if (r) r.addEventListener('click', doReview);
  if (a) a.addEventListener('click', applyDeck);
  // 组卡面板上的「AI 优化」按钮：开抽屉并直接点评当前卡组
  const suggest = document.getElementById('btnAiSuggest');
  if (suggest) suggest.addEventListener('click', () => {
    document.getElementById('btnAi').click();
    doReview();
  });
  loadIntents();
}
