// Shared helpers for all tfn-studio pages (ES module, no dependencies).

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** DOM builder: h('div', {class:'x', onclick: fn}, 'text', childEl). Text is always inserted as text. */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** Append children to `parent`, flattening arrays and skipping null/undefined/false (unlike Element.append). */
export function put(parent, ...children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    parent.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return parent;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

let sessionPromise = null;
export function session() {
  if (!sessionPromise) sessionPromise = fetch('/api/session').then(r => r.json());
  return sessionPromise;
}

/** JSON API call. Non-GET requests automatically carry the per-run token. Throws Error(message). */
export async function api(path, { method = 'GET', body } = {}) {
  const headers = {};
  if (method !== 'GET') headers['X-Studio-Token'] = (await session()).token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const resp = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  let data = null;
  try { data = await resp.json(); } catch (e) { /* non-JSON error */ }
  if (!resp.ok) throw new Error((data && data.error) || `HTTP ${resp.status}`);
  return data;
}

export function toast(message, kind = 'info', ms = 4500) {
  let box = $('#toasts');
  if (!box) { box = h('div', { id: 'toasts' }); document.body.append(box); }
  const t = h('div', { class: `toast ${kind}` }, message);
  box.append(t);
  setTimeout(() => t.remove(), kind === 'error' ? ms * 2 : ms);
}

export function debounce(fn, ms = 250) {
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// Where each page is explained in the manual (the ids are MANUAL.md's heading anchors; tests/test_mdhtml.py checks that they exist).
export const MANUAL_SECTIONS = {
  '/': '#6-dashboard', '/camps': '#7-camp-builder', '/spawns': '#8-spawn-designer', '/quests': '#9-quest-builder',
  '/changes': '#10-changes-review-apply-undo',
};
export const manualHref = page => '/manual' + (MANUAL_SECTIONS[page] || '');

/** Top navigation; call once per page. */
export async function navbar(active) {
  let info = { features: { spawns: true, random_camps: true, legacy_quest_scripts: true }, brand: 'TFN Content Studio' };
  try { info = Object.assign(info, await session()); } catch (e) { /* the bar still renders; the chip below says the server is down */ }
  // another module than The Frozen North has no spawn engine and no numbered quest scripts of its own
  const links = [['/', 'Dashboard'], ['/camps', 'Camp Builder'], ['/spawns', 'Spawn Designer'],
                 ['/quests', 'Quest Builder'], ['/changes', 'Changes']].filter(([href]) => href !== '/spawns' || info.features.spawns);
  document.title = document.title.replace(/^TFN (Studio|Content Studio)/, info.brand.replace('Content ', ''));
  const meta = h('div', { class: 'meta' });
  // opens in a new tab so an unsaved plan or draft on this page is never lost
  const manual = h('a', { href: manualHref(active), target: '_blank', rel: 'noopener', class: 'manual-link',
    title: 'Open the manual (installation, usage, troubleshooting) at this page\'s section, in a new tab' }, 'Manual ↗');
  const bar = h('header', { class: 'top' },
    h('span', { class: 'brand' }, info.brand),
    h('nav', {}, links.map(([href, label]) => h('a', { href, class: href === active ? 'active' : '' }, label)), manual),
    meta);
  document.body.prepend(bar);
  try {
    const s = await session();
    meta.append(h('span', {}, s.branch ? `${s.profile === 'generic' ? 'Module' : 'TFN'} @ ${s.branch}` : (s.profile === 'generic' ? 'Module' : 'TFN')), h('span', { class: 'mono' }, s.tfn_root));
  } catch (e) { meta.append(h('span', { class: 'chip bad' }, 'server unreachable')); }
}

/** Modal dialog. buttons: [{label, primary, value}]. Resolves with the clicked value (or null on close). */
export function modal(title, bodyEl, buttons = [{ label: 'Close', value: null }]) {
  return new Promise(resolve => {
    const done = v => { back.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = e => { if (e.key === 'Escape') done(null); };
    const back = h('div', { class: 'modal-back', onclick: e => { if (e.target === back) done(null); } },
      h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true' },
        h('header', {}, h('h3', { style: { margin: 0 } }, title), h('button', { class: 'right small', onclick: () => done(null) }, '✕')),
        h('div', { class: 'body' }, bodyEl),
        h('footer', {}, buttons.map(b => h('button', { class: b.primary ? 'primary' : (b.danger ? 'danger' : ''), onclick: () => done(b.value) }, b.label)))));
    document.addEventListener('keydown', onKey);
    document.body.append(back);
  });
}

export function issueList(issues) {
  if (!issues || !issues.length) return h('div', { class: 'muted' }, 'No issues.');
  return h('div', {}, issues.map(i => h('div', { class: `issue ${i.level}` },
    h('b', {}, i.level.toUpperCase()), ' ', i.message, i.rel ? h('span', { class: 'rel' }, i.rel) : null)));
}

export function issueCounts(issues) {
  const c = { error: 0, warning: 0, info: 0 };
  for (const i of issues || []) c[i.level] = (c[i.level] || 0) + 1;
  return c;
}

export function fmtTime(sec) {
  if (!sec) return '';
  return new Date(sec * 1000).toLocaleString();
}

export function fmtNum(n, d = 1) { return (n === null || n === undefined || Number.isNaN(n)) ? '' : Number(n).toFixed(d).replace(/\.0+$/, ''); }

/** Colour-coded unified diff element. */
export function diffView(text) {
  const box = h('div', { class: 'diff' });
  for (const line of text.split('\n')) {
    let cls = '';
    if (line.startsWith('+++') || line.startsWith('---')) cls = 'file';
    else if (line.startsWith('@@')) cls = 'hunk';
    else if (line.startsWith('+')) cls = 'add';
    else if (line.startsWith('-')) cls = 'del';
    box.append(h('div', { class: cls }, line || ' '));
  }
  return box;
}

/** Simple searchable list picker used by several pages. */
export function searchList({ items, render, onPick, placeholder = 'Search…', filter, max = 200 }) {
  const input = h('input', { type: 'text', placeholder, style: { width: '100%', marginBottom: '6px' } });
  const list = h('div', { class: 'list' });
  let selected = null;
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    clear(list);
    let n = 0;
    for (const it of items()) {
      if (filter && !filter(it, q)) continue;
      if (n++ >= max) { list.append(h('div', { class: 'item muted' }, `…more (${max} shown), refine search`)); break; }
      const row = render(it);
      row.classList.add('item');
      if (selected === it) row.classList.add('sel');
      row.addEventListener('click', () => { selected = it; draw(); onPick(it); });
      list.append(row);
    }
    if (!n) list.append(h('div', { class: 'item muted' }, 'No matches'));
  };
  input.addEventListener('input', debounce(draw, 120));
  draw();
  return { el: h('div', {}, input, list), redraw: draw, select: it => { selected = it; draw(); } };
}
