// 应用外壳：视图路由、模式切换、健康状态、AI 抽屉
import { get, toast } from './api.js';
import { initCards, setMode, initMine } from './cards.js';
import { initMeta } from './meta.js';
import { initAi } from './ai.js';

const VIEWS = [
  { id: 'viewMeta', label: '环境' },
  { id: 'viewBuilder', label: '组卡' },
  { id: 'viewMine', label: '我的' },
];

let currentMode = 'standard';

// ---------------------------------------------------------------- 路由
function switchView(id) {
  VIEWS.forEach(v => {
    const el = document.getElementById(v.id);
    el.classList.toggle('active', v.id === id);
  });
  document.querySelectorAll('.tabbar button').forEach(b =>
    b.setAttribute('aria-current', String(b.dataset.view === id)));
  // 桌面端没有底部 Tab，补一排顶部导航按钮组
  document.querySelectorAll('.desknav button').forEach(b =>
    b.setAttribute('aria-current', String(b.dataset.view === id)));
}

function initNav() {
  // 移动端底部 Tab + 桌面端顶部导航，统一绑定
  document.querySelectorAll('[data-view]').forEach(btn => {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
  });

  document.getElementById('btnAi').addEventListener('click', () => openDrawer(true));
  document.getElementById('btnCloseDrawer').addEventListener('click', () => openDrawer(false));
  document.getElementById('scrim').addEventListener('click', () => openDrawer(false));
}

function openDrawer(open) {
  document.getElementById('drawer').classList.toggle('open', open);
  document.getElementById('scrim').classList.toggle('show', open);
  document.getElementById('drawer').setAttribute('aria-hidden', String(!open));
}

// ---------------------------------------------------------------- 模式
function initMode() {
  document.querySelectorAll('#modeSeg button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#modeSeg button').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
      currentMode = btn.dataset.mode;
      setMode(currentMode);
      refreshMetaHint();
    });
  });
}

// ---------------------------------------------------------------- 状态条
async function loadHealth() {
  try {
    const h = await get('/health');
    const ai = h.ai.configured ? `<span class="status-dot ok"></span>AI 已配置` : `<span class="status-dot warn"></span>AI 未配置`;
    const db = h.db.cards > 0 ? `<span class="status-dot ok"></span>卡池 ${h.db.cards} 张` : `<span class="status-dot warn"></span>卡池待入库`;
    document.getElementById('healthHint').innerHTML = `${db}　${ai}`;
    document.getElementById('metaSub').innerHTML =
      `数据版本 ${h.sets_config_version || '-'} · 手机可用 <code style="color:var(--gold-bright)">${h.access.lan}</code> 访问`;
  } catch (e) {
    document.getElementById('healthHint').innerHTML = `<span class="status-dot bad"></span>服务未就绪`;
  }
}

function refreshMetaHint() {
  const list = document.getElementById('metaDeckList');
  if (!list.dataset.ready) return;
}

// ---------------------------------------------------------------- 环境页（阶段⑤⑥接通数据）
function initMetaPlaceholder() {
  // 环境模块已接通 HSReplay，占位逻辑保留为兜底（脚本未加载时提示）
  const list = document.getElementById('metaDeckList');
  list.innerHTML = `
    <div class="panel empty-state">
      <h3>环境数据加载中…</h3>
      <div>首次进入会自动抓取 HSReplay 当前版本环境数据。</div>
    </div>`;
}



// ---------------------------------------------------------------- 启动
function boot() {
  VIEWS.forEach(v => { document.getElementById(v.id).classList.remove('active'); });
  switchView('viewMeta');
  initNav();
  initMode();
  initCards();
  initMine();
  initMeta();
  initAi();
  loadHealth();
}

document.addEventListener('DOMContentLoaded', boot);
