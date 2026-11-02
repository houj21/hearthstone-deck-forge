// 环境视图：HSReplay 真实胜率数据（胜率/样本/占比/节奏/卡组码）
import { get, post, toast } from './api.js';

const BUCKET_CN = {
  TOP1000_LEGEND: '前千传说',
  LEGEND: '传说',
  DIAMOND_TO_L5: '钻石~传说5',
  GOLD_TO_PLATINUM: '黄金~铂金',
  BRONZE_TO_SILVER: '青铜~白银',
  CASUAL: '休闲/新手',
};

const state = { window: 'current', bucket: '', entries: [], status: null };

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function bucketCn(id) { return BUCKET_CN[id] || id; }

function agoText(updatedAt) {
  if (!updatedAt) return '';
  const mins = Math.max(0, Math.round((Date.now() - new Date(updatedAt).getTime()) / 60000));
  if (mins < 1) return '刚刚更新';
  if (mins < 60) return `${mins} 分钟前更新`;
  return `${Math.floor(mins / 60)} 小时前更新`;
}

function fillSelect(el, options, current) {
  if (!el) return;
  el.innerHTML = options.map(o => `<option value="${o.id}"${o.id === current ? ' selected' : ''}>${escapeHtml(o.label)}</option>`).join('');
}

async function loadStatus() {
  state.status = await get('/meta/status');
  fillSelect(
    document.getElementById('metaWindowSel'),
    state.status.time_windows || [],
    state.window,
  );
  const bucketSel = document.getElementById('bucketSel');
  fillSelect(
    bucketSel,
    [{ id: '', label: '全部分段' }].concat(state.status.buckets || []),
    state.bucket,
  );
}

async function loadSummary({ autoRefresh = true } = {}) {
  const titleEl = document.getElementById('metaTitle');
  const subEl = document.getElementById('metaSub');
  let data;
  try {
    data = await get('/meta/summary', { mode: 'standard', window: state.window });
  } catch {
    return;
  }
  if (!data.ok && autoRefresh) {                 // 首次进入自动抓一轮
    subEl.textContent = '首次加载，正在抓取 HSReplay 环境数据…';
    await refreshMeta();
    return loadSummary({ autoRefresh: false });
  }
  state.entries = data.entries || [];
  const src = (data.source_status && data.source_status.sources) || [];
  const patch = src.length ? '' : '';
  titleEl.textContent = `天梯环境 · ${data.window_label || '当前版本'}`;
  subEl.textContent = [
    `HSReplay 青铜~黄金${data.stale ? '（数据已过期）' : ''}`,
    `${data.entry_count || state.entries.length} 个卡组原型`,
    agoText(data.updated_at),
    data.source_status && data.source_status.degraded ? '降级显示本地留档' : '',
  ].filter(Boolean).join(' · ');
  renderList();
}

async function loadRecommend() {
  const grid = document.getElementById('metaRecommend');
  const subEl = document.getElementById('recommendSub');
  if (!grid) return;
  let data;
  try {
    data = await get('/recommend', { mode: 'standard', window: state.window, bucket: state.bucket });
  } catch { return; }
  if (!data.ok || !data.items.length) {
    grid.innerHTML = `<div class="panel empty-state"><h3>暂无推荐</h3><div>${escapeHtml(data.message || '换个时间窗或分段试试')}</div></div>`;
    subEl.textContent = '';
    return;
  }
  document.getElementById('recommendTitle').textContent =
    `推荐上分 · ${escapeHtml(data.bucket_label || '全部分段')}`;
  subEl.textContent = `${data.window_label} · 环境均值 ${data.prior_win_rate}%`;
  grid.innerHTML = data.items.map((e, i) => `
    <div class="panel deck-card">
      <div class="row1">
        <strong>${i + 1}. ${escapeHtml(e.name || e.name_en || '')}</strong>
        <span class="class-badge ${e.card_class || ''}">${escapeHtml(e.card_class_cn || e.card_class || '')}</span>
      </div>
      <div class="metric-row">
        <span>胜率 <b>${Number(e.win_rate || 0).toFixed(1)}%</b></span>
        <span>评分 ${Number(e.score || 0).toFixed(1)}</span>
        <span>样本 ${(e.sample_size || 0).toLocaleString()}</span>
      </div>
      <div style="color:var(--text-faint);font-size:12px;margin:6px 0">${escapeHtml(e.reason || '')}</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn primary" data-import="${escapeHtml(e.deck_code || '')}">一键导入组卡器</button>
        <button class="btn ghost" data-code="${escapeHtml(e.deck_code || '')}">复制卡组码</button>
      </div>
    </div>`).join('');
}

function renderList() {
  const grid = document.getElementById('metaDeckList');
  const list = state.bucket
    ? state.entries.filter(e => (e.buckets || []).includes(state.bucket))
    : state.entries;
  if (!list.length) {
    grid.innerHTML = `<div class="panel empty-state"><h3>暂无数据</h3><div>换个时间窗或点「刷新环境」重试</div></div>`;
    return;
  }
  grid.innerHTML = list.map((e, i) => {
    const trend = Number(e.trend || 0);
    const trendHtml = Math.abs(trend) < 0.05 ? '' :
      `<span style="color:${trend > 0 ? 'var(--ok,#5ddc9a)' : 'var(--warn)'}">${trend > 0 ? '▲' : '▼'} ${Math.abs(trend).toFixed(1)}%</span>`;
    const buckets = (e.buckets || []).map(b => `<span class="chip">${escapeHtml(bucketCn(b))}</span>`).join('');
    return `
      <div class="panel deck-card" data-idx="${i}">
        <div class="row1">
          <strong>${escapeHtml(e.name || e.name_en || '未命名原型')}</strong>
          <span class="class-badge ${e.card_class || ''}">${escapeHtml(e.card_class_cn || e.card_class || '')}</span>
        </div>
        <div class="metric-row">
          <span>胜率 <b>${Number(e.win_rate || 0).toFixed(1)}%</b></span>
          <span>样本 ${(e.sample_size || 0).toLocaleString()}</span>
          <span>占比 ${Number(e.share || 0).toFixed(1)}%</span>
          ${trendHtml}
        </div>
        <div class="metric-row" style="color:var(--text-faint)">
          <span>${escapeHtml(e.style_cn || '')}节奏</span>
          <span>均时 ${Math.round((e.avg_game_length || 0) / 60)}分${(e.avg_game_length || 0) % 60}秒</span>
          <span>${e.deck_count || 0} 套样本</span>
        </div>
        <div class="chips" style="margin:6px 0">${buckets}</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn" data-import="${escapeHtml(e.deck_code || '')}">导入组卡器</button>
          <button class="btn ghost" data-code="${escapeHtml(e.deck_code || '')}">复制卡组码</button>
        </div>
      </div>`;
  }).join('');
}

async function refreshMeta() {
  const btn = document.getElementById('btnRefreshMeta');
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = '抓取中…';
  try {
    const r = await post(`/meta/refresh?mode=standard&window=${state.window}`);
    if (!r.ok) { toast(r.message || '刷新失败'); return; }
    toast(`已更新 ${r.entry_count} 个卡组原型${r.degraded ? '（降级留档）' : ''}`);
    await loadSummary({ autoRefresh: false });
    await loadRecommend();
  } catch {
    /* get/post 已提示 */
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

function copyText(text) {
  try { navigator.clipboard.writeText(text); } catch {
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove();
  }
}

export function initMeta() {
  // 事件委托到 document：环境榜与推荐榜的按钮共用同一套 data-* 行为
  document.addEventListener('click', e => {
    const imp = e.target.closest('[data-import]');
    if (imp && imp.dataset.import) {
      const input = document.getElementById('deckCodeInput');
      if (input) {
        input.value = imp.dataset.import;
        document.getElementById('btnImportCode').click();
        document.querySelector('[data-view="viewBuilder"]').click();
      }
      return;
    }
    const cp = e.target.closest('[data-code]');
    if (cp && cp.dataset.code) { copyText(cp.dataset.code); toast('卡组码已复制'); }
  });

  const winSel = document.getElementById('metaWindowSel');
  if (winSel) winSel.addEventListener('change', () => {
    state.window = winSel.value;
    loadSummary().then(loadRecommend);
  });
  const bucketSel = document.getElementById('bucketSel');
  if (bucketSel) bucketSel.addEventListener('change', () => {
    state.bucket = bucketSel.value;
    renderList();
    loadRecommend();
  });
  document.getElementById('btnRefreshMeta').addEventListener('click', refreshMeta);

  loadStatus().then(() => loadSummary().then(loadRecommend)).catch(() => { });
}

export function getMetaEntries() { return state.entries; }
