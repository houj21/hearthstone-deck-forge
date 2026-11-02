// 卡池浏览 + 当前卡组（加入/移除/曲线/尘数），本地草稿存 localStorage
import { get, post, toast } from './api.js';

const KEYWORDS = ['战吼', '亡语', '嘲讽', '圣盾', '突袭', '吸血', '发现', '冻结', '复生', '剧毒', '过载', '抉择'];
const RARITIES = [
  { id: 'COMMON', name: '普通' },
  { id: 'RARE', name: '稀有' },
  { id: 'EPIC', name: '史诗' },
  { id: 'LEGENDARY', name: '传说' },
];
const STORAGE_KEY = 'hs.deck.draft';

const state = {
  mode: 'standard',
  cardClass: 'MAGE',
  q: '',
  costMax: null,
  keyword: '',
  rarity: '',
  sort: 'cost',
  page: 1,
  total: 0,
  items: [],
  deck: loadDeck(),      // { [dbf_id]: { card, qty } }
  selected: null,        // 换卡建议的目标卡
};

// ---------------------------------------------------------------- 卡组持久化
function loadDeck() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch { return {}; }
}
function saveDeck() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state.deck)); } catch { }
}
function deckSize() {
  return Object.values(state.deck).reduce((s, x) => s + x.qty, 0);
}
function deckCards() {
  return Object.values(state.deck).map(x => ({ ...x.card, qty: x.qty }));
}

// ---------------------------------------------------------------- 卡池加载
async function loadPool({ reset = true } = {}) {
  if (reset) state.page = 1;
  const res = await get('/cards', {
    card_class: state.cardClass,
    mode: state.mode,
    q: state.q || null,
    cost_max: state.costMax,
    keyword: state.keyword || null,
    rarities: state.rarity || null,
    sort: state.sort,
    page: state.page,
    page_size: 48,
  });
  state.total = res.total;
  state.items = reset ? res.items : state.items.concat(res.items);
  renderPool();
}

function renderPool() {
  const grid = document.getElementById('cardGrid');
  const count = document.getElementById('poolCount');
  count.textContent = `共 ${state.total} 张` + (state.items.length < state.total ? `（已显示 ${state.items.length}）` : '');
  document.getElementById('btnMore').style.display = state.items.length < state.total ? '' : 'none';

  grid.innerHTML = state.items.map(c => {
    const qty = state.deck[c.dbf_id]?.qty || 0;
    const stats = c.type === 'MINION'
      ? `${c.attack}/${c.health}`
      : c.type === 'WEAPON' ? `${c.attack}/${c.durability}`
        : c.type === 'HERO' ? `${c.armor} 护甲` : '';
    const rarityClass = 'rarity-' + (c.rarity || '').toLowerCase();
    return `
      <div class="mini-card" data-dbf="${c.dbf_id}">
        <div class="cost-crystal">${c.cost ?? '-'}</div>
        <div class="mini-main">
          <div class="mini-name ${rarityClass}">${escapeHtml(c.name)}${qty ? `<span class="mini-count">×${qty}</span>` : ''}</div>
          <div class="mini-meta">${stats ? stats + ' · ' : ''}${typeCn(c.type)}${c.runes ? ' · ' + c.runes : ''}</div>
          <div class="mini-text">${escapeHtml(c.text || '')}</div>
        </div>
      </div>`;
  }).join('') || `<div class="empty-state"><h3>没有符合条件的卡</h3><div>换个筛选条件试试</div></div>`;
}

// ---------------------------------------------------------------- 卡组操作
function addCard(card) {
  const cur = state.deck[card.dbf_id];
  if (cur) {
    const max = card.rarity === 'LEGENDARY' ? 1 : 2;
    if (cur.qty >= max) { toast(`「${card.name}」已达上限（${max} 张）`); return; }
  } else if (deckSize() >= 30) {
    toast('卡组已满 30 张');
    return;
  }
  state.deck[card.dbf_id] = { card, qty: cur ? cur.qty + 1 : 1 };
  saveDeck();
  renderPool();
  renderDeck();
}

function removeCard(dbfId) {
  const cur = state.deck[dbfId];
  if (!cur) return;
  if (cur.qty > 1) cur.qty -= 1;
  else delete state.deck[dbfId];
  saveDeck();
  renderPool();
  renderDeck();
}

function renderDeck() {
  const list = document.getElementById('deckList');
  const counter = document.getElementById('deckCount');
  const size = deckSize();
  counter.textContent = `${size}/30`;
  counter.classList.toggle('full', size === 30);

  const rows = deckCards().sort((a, b) => (a.cost ?? 0) - (b.cost ?? 0) || a.name.localeCompare(b.name));
  list.innerHTML = rows.length
    ? rows.map(c => `
        <div class="deck-row" data-dbf="${c.dbf_id}" title="点击移除一张">
          <span class="dc">${c.cost ?? '-'}</span>
          <span class="rarity-${(c.rarity || '').toLowerCase()}">${escapeHtml(c.name)}</span>
          <span class="qn">${c.qty > 1 ? '×' + c.qty : ''}</span>
        </div>`).join('')
    : `<div class="deck-row empty-row">卡组是空的，点左边卡池添加卡牌</div>`;

  document.getElementById('dustTotal').textContent = rows.reduce((s, c) => s + (c.dust_cost || 0) * c.qty, 0);
  renderCurve(rows);
}

function renderCurve(rows) {
  const el = document.getElementById('curve');
  const buckets = Array(8).fill(0);   // 0..6, 7+
  rows.forEach(c => { const k = Math.min(c.cost ?? 0, 7); buckets[k] += c.qty; });
  const max = Math.max(1, ...buckets);
  el.innerHTML = buckets.map((n, i) => `
    <div class="curve-bar" style="height:${Math.max(3, (n / max) * 100)}%">
      <span>${i === 7 ? '7+' : i}</span>
    </div>`).join('');
}

// ---------------------------------------------------------------- 初始化
export function initCards() {
  const classSel = document.getElementById('classSel');
  const qInput = document.getElementById('qInput');
  const costRange = document.getElementById('costRange');
  const sortSel = document.getElementById('sortSel');

  get('/cards/classes').then(d => {
    classSel.innerHTML = d.items.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
    classSel.value = state.cardClass;
  });

  document.getElementById('keywordChips').innerHTML =
    KEYWORDS.map(k => `<button class="chip" data-kw="${k}">${k}</button>`).join('');
  document.getElementById('rarityChips').innerHTML =
    RARITIES.map(r => `<button class="chip" data-rarity="${r.id}">${r.name}</button>`).join('');

  classSel.addEventListener('change', () => { state.cardClass = classSel.value; loadPool(); });
  sortSel.addEventListener('change', () => { state.sort = sortSel.value; loadPool(); });
  costRange.addEventListener('input', () => {
    const v = Number(costRange.value);
    state.costMax = v >= 30 ? null : v;
    document.getElementById('costLabel').textContent = v >= 30 ? '全部' : `${v} 及以下`;
    debouncedLoad();
  });

  let timer = null;
  function debouncedLoad() {
    clearTimeout(timer);
    timer = setTimeout(() => loadPool(), 250);   // 搜索防抖
  }
  qInput.addEventListener('input', () => { state.q = qInput.value.trim(); debouncedLoad(); });

  document.getElementById('keywordChips').addEventListener('click', e => {
    const btn = e.target.closest('.chip'); if (!btn) return;
    const kw = btn.dataset.kw;
    const on = state.keyword === kw;
    state.keyword = on ? '' : kw;
    document.querySelectorAll('#keywordChips .chip').forEach(c => c.setAttribute('aria-pressed', String(c.dataset.kw === state.keyword)));
    loadPool();
  });
  document.getElementById('rarityChips').addEventListener('click', e => {
    const btn = e.target.closest('.chip'); if (!btn) return;
    const r = btn.dataset.rarity;
    state.rarity = state.rarity === r ? '' : r;
    document.querySelectorAll('#rarityChips .chip').forEach(c => c.setAttribute('aria-pressed', String(c.dataset.rarity === state.rarity)));
    loadPool();
  });

  document.getElementById('btnResetFilter').addEventListener('click', () => {
    state.q = ''; state.costMax = null; state.keyword = ''; state.rarity = '';
    qInput.value = ''; costRange.value = 30;
    document.getElementById('costLabel').textContent = '全部';
    document.querySelectorAll('.chip').forEach(c => c.setAttribute('aria-pressed', 'false'));
    loadPool();
  });

  document.getElementById('btnMore').addEventListener('click', () => { state.page += 1; loadPool({ reset: false }); });

  document.getElementById('cardGrid').addEventListener('click', e => {
    const el = e.target.closest('.mini-card'); if (!el) return;
    const card = state.items.find(c => String(c.dbf_id) === el.dataset.dbf);
    if (card) addCard(card);
  });

  document.getElementById('deckList').addEventListener('click', e => {
    const el = e.target.closest('.deck-row[data-dbf]'); if (!el) return;
    removeCard(Number(el.dataset.dbf));
  });

  // 右键（手机长按）选中某张卡作为「换卡建议」的目标
  document.getElementById('deckList').addEventListener('contextmenu', e => {
    const el = e.target.closest('.deck-row[data-dbf]'); if (!el) return;
    e.preventDefault();
    const dbf = Number(el.dataset.dbf);
    const row = state.deck[dbf];
    if (row) {
      setSelected(row.card);
      document.getElementById('drawer')?.classList.add('open');
      document.getElementById('scrim')?.classList.add('show');
      toast(`已选中「${row.card.name}」，可在 AI 面板提换卡要求`);
    }
  });

  document.getElementById('btnClearDeck').addEventListener('click', () => {
    state.deck = {}; saveDeck(); renderPool(); renderDeck(); showIssues([]);
  });

  // 卡组码：导入 / 导出
  document.getElementById('btnImportCode').addEventListener('click', async () => {
    const code = document.getElementById('deckCodeInput').value.trim();
    if (!code) { toast('请先粘贴卡组码'); return; }
    try {
      let data = await post('/decks/parse', { code, mode: state.mode });
      // 卡组里有已轮换的卡时，自动切到狂野再解析一次，避免误判成「导入失败」
      if ((data.errors || []).some(e => e.includes('标准模式下不可使用')) && state.mode === 'standard') {
        state.mode = 'wild';
        document.querySelectorAll('#modeSeg button').forEach(b =>
          b.setAttribute('aria-pressed', String(b.dataset.mode === 'wild')));
        toast('该卡组含已轮换的卡，已切到狂野模式');
        await loadPool();
        data = await post('/decks/parse', { code, mode: 'wild' });
      }
      state.deck = {};
      (data.items || []).forEach(c => { state.deck[c.dbf_id] = { card: c, qty: c.qty }; });
      saveDeck(); renderPool(); renderDeck();
      showIssues([...(data.errors || []), ...(data.warnings || [])]);
      toast(`已导入 ${data.total} 张 · ${data.card_class || '未知职业'}`);
    } catch (e) {
      showIssues([String(e.message || e)]);
    }
  });

  document.getElementById('btnExportCode').addEventListener('click', async () => {
    const entries = Object.values(state.deck).map(x => ({ dbf_id: x.card.dbf_id, qty: x.qty }));
    if (!entries.length) { toast('卡组还是空的'); return; }
    const data = await post('/decks/encode', {
      card_class: state.cardClass,
      mode: state.mode,
      fmt: state.mode === 'wild' ? 'wild' : 'standard',
      cards: entries,
    });
    document.getElementById('deckCodeInput').value = data.deck_code;
    copyText(data.deck_code);
    showIssues([...(data.errors || []), ...(data.warnings || [])]);
    toast('卡组码已生成并复制');
  });

  renderDeck();
  loadPool();
}

export function setMode(mode) {
  state.mode = mode;
  loadPool();
}

export function currentDeck() {
  return deckCards();
}

// 供 AI 教练取当前上下文（职业 / 模式）
export function deckContext() {
  return { card_class: state.cardClass, mode: state.mode };
}

export function setDeckFromCode(cards) {
  // cards: [{ card, qty }]，由卡组码解析后调用
  state.deck = {};
  cards.forEach(c => { state.deck[c.card.dbf_id] = { card: c.card, qty: c.qty }; });
  saveDeck();
  renderPool();
  renderDeck();
}

export function setSelected(card) {
  state.selected = card;
  const el = document.getElementById('swapTarget');
  if (el) el.innerHTML = card
    ? `<span class="rarity-${(card.rarity || '').toLowerCase()}">${escapeHtml(card.name)}</span> <span style="color:var(--text-faint)">（${card.cost} 费）</span>`
    : '未选择';
}

export function getSelected() { return state.selected; }

function typeCn(t) {
  return { MINION: '随从', SPELL: '法术', WEAPON: '武器', HERO: '英雄', LOCATION: '地点' }[t] || t || '';
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ---------------------------------------------------------------- 提示与工具
function showIssues(list) {
  const el = document.getElementById('deckIssues');
  if (!el) return;
  const errs = (list || []).filter(Boolean);
  el.innerHTML = errs.length
    ? errs.map(t => `<div style="color:var(--warn)">· ${escapeHtml(t)}</div>`).join('')
    : '';
}

function copyText(text) {
  try {
    navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove();
  }
}

// ---------------------------------------------------------------- 我的卡组
export function initMine() {
  const listEl = document.getElementById('mineList');
  const countEl = document.getElementById('mineCount');

  async function refresh() {
    const data = await get('/decks/saved');
    countEl.textContent = `${data.items.length} 套`;
    listEl.innerHTML = data.items.length
      ? data.items.map(d => `
        <div class="panel deck-card">
          <div class="row1">
            <strong>${escapeHtml(d.name)}</strong>
            <span class="class-badge ${d.card_class || ''}">${d.card_class || '未知'}</span>
          </div>
          <div class="metric-row">
            <span>${d.mode === 'wild' ? '狂野' : '标准'}</span>
            <span>卡组码 <b style="font-size:12px">${escapeHtml((d.deck_code || '').slice(0, 16))}…</b></span>
          </div>
          <div style="display:flex;gap:8px">
            <button class="btn" data-load="${d.id}">载入组卡器</button>
            <button class="btn ghost" data-code="${escapeHtml(d.deck_code || '')}">复制卡组码</button>
          </div>
        </div>`).join('')
      : `<div class="panel empty-state"><h3>还没有保存的卡组</h3><div>组好一套后点上方「保存当前卡组」</div></div>`;
  }

  listEl.addEventListener('click', async e => {
    const loadBtn = e.target.closest('[data-load]');
    if (loadBtn) {
      const d = await get('/decks/saved/' + loadBtn.dataset.load);
      if (d.deck_code) {
        document.getElementById('deckCodeInput').value = d.deck_code;
        document.getElementById('btnImportCode').click();
        document.querySelector('[data-view="viewBuilder"]').click();
      }
      return;
    }
    const codeBtn = e.target.closest('[data-code]');
    if (codeBtn && codeBtn.dataset.code) { copyText(codeBtn.dataset.code); toast('卡组码已复制'); }
  });

  document.getElementById('btnSaveDeck').addEventListener('click', async () => {
    const entries = Object.values(state.deck).map(x => ({ dbf_id: x.card.dbf_id, qty: x.qty }));
    if (!entries.length) { toast('卡组是空的'); return; }
    const name = document.getElementById('deckNameInput').value.trim() || '未命名卡组';
    await post('/decks/save', { name, card_class: state.cardClass, mode: state.mode, cards: entries });
    toast('已保存到本地');
    refresh();
  });

  refresh();
  return refresh;
}

export { toast };
