// 统一接口封装：自动补 /api 前缀、统一错误提示、返回 JSON
const BASE = '/api';

let toastTimer = null;
export function toast(msg) {
  const wrap = document.getElementById('toastWrap');
  if (!wrap) return;
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  wrap.appendChild(el);
  clearTimeout(toastTimer);
  setTimeout(() => el.remove(), 2400);
}

function buildURL(path, params = {}) {
  const u = new URL(BASE + path, location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return;
    if (Array.isArray(v)) v.forEach(x => u.searchParams.append(k, x));
    else u.searchParams.set(k, v);
  });
  return u.toString();
}

export async function get(path, params) {
  const res = await fetch(buildURL(path, params));
  if (!res.ok) {
    const msg = await safeMessage(res);
    toast(`请求失败：${msg}`);
    throw new Error(msg);
  }
  return res.json();
}

export async function post(path, body) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const msg = await safeMessage(res);
    toast(`请求失败：${msg}`);
    throw new Error(msg);
  }
  return res.json();
}

// SSE：用于 AI 流式输出（网关长响应必须流式）
export function stream(path, params, { onDelta, onDone, onError, onStatus }) {
  const url = buildURL(path, params);
  const es = new EventSource(url);
  es.onmessage = ev => {
    try {
      const data = JSON.parse(ev.data);
      if (data.type === 'delta') onDelta && onDelta(data.text, data);
      else if (data.type === 'status') onStatus && onStatus(data.text);
      else if (data.type === 'done') { onDone && onDone(data); es.close(); }
      else if (data.type === 'error') { onError && onError(data.message); es.close(); }
      else if (data.type === 'result') { onDone && onDone(data); }
    } catch (e) {
      // 非 JSON 增量按纯文本处理
      onDelta && onDelta(ev.data, {});
    }
  };
  es.onerror = () => { es.close(); onError && onError('连接中断'); };
  return es;
}

async function safeMessage(res) {
  try {
    const d = await res.json();
    return d.detail || d.message || ('HTTP ' + res.status);
  } catch {
    return 'HTTP ' + res.status;
  }
}
