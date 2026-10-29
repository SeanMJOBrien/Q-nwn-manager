import { $, $$, h, api, clear, navbar, toast, modal, searchList, issueList, issueCounts, fmtNum, put } from '/static/common.js';
import { AreaMap, KIND_COLOR, xformPoint } from '/static/areamap.js';
import { createUteEditor, blankSpec } from '/static/uteeditor.js';

const app = $('#app');
await navbar('/camps');
app.className = 'full';

const [areas, palette, creatures, prefabs, utes, savedPlans] = await Promise.all([
  api('/api/areas'), api('/api/palette/placeables'), api('/api/palette/creatures?base=1'), api('/api/prefabs'),
  api('/api/utes'), api('/api/specs/camps')]);
const creatureBy = Object.fromEntries(creatures.map(c => [c.resref, c]));
const uteNames = () => [...utes.map(u => u.resref), ...S.plan.new_utes.map(u => u.resref)];

const slug = t => t.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 32);
const r2 = v => Math.round(v * 100) / 100;
const r4 = v => Math.round(v * 10000) / 10000;

const MAX_SPOTS = 24;
const newPlan = () => ({ id: '', title: '', area: '', cr: null, objects: [], groups: [], events: [], event_chance: null, new_utes: [], camp_event: null });
const newCampEvent = () => ({ script: '', weight: 1, origin: null, spots: [], include_origin: false, replaces_group: null, replace_radius: 0 });
const S = {
  areaInfo: null, detail: null, plan: newPlan(), tool: { type: 'select' }, sel: null,
  history: [], stamp: 1, rotation: 0, gmap: {}, idTouched: false,
  spotSel: null, eventInfo: null, eventError: '', seed: 1,
};

// ------------------------------------------------------------------ layout
const left = h('div', { class: 'pane-left' });
const centerPane = h('div', { class: 'pane-center' });
const right = h('div', { class: 'pane-right' });
put(app, left, centerPane, right);

const canvas = h('canvas', { tabindex: 0 });
const hud = h('div', { class: 'maphud' }, 'choose an area');
const mapwrap = h('div', { class: 'mapwrap' }, canvas, hud,
  h('div', { class: 'legend' }, Object.entries({ placeable: 'prop', creature: 'creature', marker: 'spawn marker', waypoint: 'waypoint', door: 'door', spot: 'camp spot' })
    .map(([k, label]) => h('div', {}, h('i', { style: { background: KIND_COLOR[k] } }), label))));
const toolbar = h('div', { class: 'toolbar' });
put(centerPane, toolbar, mapwrap);

const map = new AreaMap(canvas, {
  onHover: (x, y) => { hover(x, y); },
  onClick: (x, y) => place(x, y),
  onPick: i => { S.sel = i >= 0 ? i : null; S.spotSel = null; refreshSelection(); syncCamp(); highlightSpotRow(); },
  onMove: (i, x, y, final) => moveObject(i, x, y, final),
  onSpotPick: i => selectSpot(i),
  onSpotMove: (i, x, y, final) => moveSpot(i, x, y, final),
  onView: () => hudUpdate(),
});
let hoverPos = null;

// ----------------------------------------------------------------- history
function snapshot() { return JSON.stringify({ o: S.plan.objects, g: S.plan.groups, e: S.plan.events, n: S.plan.new_utes, cr: S.plan.cr, ce: S.plan.camp_event }); }
function pushHistory() { S.dirty = true; S.history.push(snapshot()); if (S.history.length > 60) S.history.shift(); }
function undo() {
  const last = S.history.pop();
  if (!last) { toast('Nothing to undo'); return; }
  const v = JSON.parse(last);
  Object.assign(S.plan, { objects: v.o, groups: v.g, events: v.e, new_utes: v.n, cr: v.cr, camp_event: v.ce ?? null });
  S.sel = null; S.spotSel = null; redrawAll();
}

// -------------------------------------------------------------- tool state
function setTool(t) {
  S.tool = t;
  map.setTool(t.type === 'select' ? 'select' : 'place');
  map.setGhost(null);
  renderToolbar(); renderTabs();
}

function toolLabel() {
  const t = S.tool;
  if (t.type === 'select') return 'Select: click an object, drag to move';
  if (t.type === 'prefab') return `Stamp prefab "${t.id}" (R rotates)`;
  if (t.type === 'marker') return `Spawn marker for group ${t.group}`;
  if (t.type === 'spot') return `Camp spot: click to add, facing ${S.rotation}° (R rotates)`;
  if (t.type === 'pivot') return 'Click to set the camp\'s pivot (the point spots move and turn it about)';
  return `Place ${t.type}: ${t.resref}`;
}

function ghostItems(x, y) {
  const t = S.tool;
  if (t.type === 'prefab') return stampPrefab(prefabs.find(p => p.id === t.id), x, y, S.rotation, S.gmap);
  if (t.type === 'marker') return [{ kind: 'marker', group: t.group, x, y, facing: 0 }];
  if (t.type === 'spot') {
    const o = effOrigin(), sp = { x, y, facing: S.rotation };
    return [...(o ? templateObjects().map(tp => ({ kind: tp.kind, resref: tp.resref, ...xformPoint(tp, o, sp) })) : []), { kind: 'spot', x, y, facing: S.rotation }];
  }
  if (t.type === 'pivot') return [{ kind: 'pivot', x, y, facing: (effOrigin() || { facing: 90 }).facing }];
  if (['placeable', 'creature', 'waypoint'].includes(t.type)) return [{ kind: t.type, resref: t.resref, x, y, facing: S.rotation }];
  return null;
}

function stampPrefab(pf, x, y, rot, gmap) {
  const rad = rot * Math.PI / 180, c = Math.cos(rad), s = Math.sin(rad);
  return pf.items.map(it => {
    const o = { kind: it.kind, x: r4(x + it.dx * c - it.dy * s), y: r4(y + it.dx * s + it.dy * c), z: null,
                facing: r2((((it.facing + rot) % 360) + 360) % 360) };
    if (it.kind === 'marker') o.group = gmap[it.group] ?? it.group; else o.resref = it.resref;
    if (it.tag) o.tag = it.tag;
    return o;
  });
}

function hover(x, y) {
  hoverPos = x === null ? null : { x, y };
  hudUpdate();
  if (x === null || S.tool.type === 'select') { map.setGhost(null); return; }
  const [sx, sy] = map.snapPoint(x, y);
  map.setGhost(ghostItems(sx, sy));
}

function hudUpdate() {
  if (!S.detail) { hud.textContent = 'choose an area'; return; }
  const sc = map.view.scale;
  let t = `scale ${sc.toFixed(1)} px/m`;
  if (hoverPos) {
    const [x, y] = map.snapPoint(hoverPos.x, hoverPos.y);
    const inside = map.inBounds(x, y);
    const tx = Math.floor(x / 10), ty = Math.floor(y / 10);
    const w = map.walkAt(x, y);
    t = `x ${x.toFixed(1)}  y ${y.toFixed(1)}${inside ? `  tile ${tx},${ty}` : '  (outside)'}${w === null ? '' : w === 1 ? '  walkable' : w === 0 ? '  NOT walkable' : ''}  ·  ` + t;
  }
  hud.textContent = t + '  ·  ' + toolLabel();
}

// ----------------------------------------------------------------- editing
function place(x, y) {
  if (!S.detail) { toast('Choose an area first', 'warn'); return; }
  if (S.tool.type === 'spot') { addSpot(x, y); return; }
  if (S.tool.type === 'pivot') { setPivot(x, y); return; }
  const items = ghostItems(x, y);
  if (!items || !items.length) return;
  const out = items.filter(i => map.inBounds(i.x, i.y, 0.5));
  if (out.length < items.length) toast(`${items.length - out.length} object(s) fall outside the area and were skipped`, 'warn');
  if (!out.length) return;
  pushHistory();
  const stamp = S.tool.type === 'prefab' ? S.stamp++ : undefined;
  const first = S.plan.objects.length;
  for (const o of out) {
    const obj = { kind: o.kind, x: o.x, y: o.y, z: null, facing: o.facing };
    if (o.kind === 'marker') obj.group = o.group; else obj.resref = o.resref;
    if (o.tag) obj.tag = o.tag;
    if (stamp) obj._stamp = stamp;
    S.plan.objects.push(obj);
  }
  ensureGroups(out.filter(o => o.kind === 'marker').map(o => o.group));
  S.sel = first + out.length - 1;
  redrawAll();
}

function ensureGroups(nums) {
  for (const n of new Set(nums)) {
    const area = (S.areaInfo.groups || []).find(g => g.n === n);
    if (!S.plan.groups.some(g => g.n === n) && !area) S.plan.groups.push({ n, ute: '', spawns: 6, script: '' });
  }
}

function moveObject(i, x, y, final) {
  const o = S.plan.objects[i];
  if (!o) return;
  if (!S._moving) { pushHistory(); S._moving = true; }
  o.x = r4(x); o.y = r4(y);
  if (final) S._moving = false;
  map.setPlan(S.plan.objects);
  syncCamp();
  if (final) { refreshSelection(); renderCamp(); eventInfoSoon(); }
}

function removeSelected() {
  if (S.sel === null && S.spotSel !== null) { removeSpot(S.spotSel); return; }
  if (S.sel === null) return;
  pushHistory();
  S.plan.objects.splice(S.sel, 1);
  S.sel = null; redrawAll();
}

function stampIndices(i) {
  const o = S.plan.objects[i];
  if (!o || !o._stamp) return [i];
  return S.plan.objects.map((p, k) => p._stamp === o._stamp ? k : -1).filter(k => k >= 0);
}

function rotateSelected(deg, wholeStamp = false) {
  if (S.sel === null && S.spotSel !== null) { rotateSpot(S.spotSel, deg); return; }
  if (S.sel === null) return;
  pushHistory();
  const idx = wholeStamp ? stampIndices(S.sel) : [S.sel];
  const cx = idx.reduce((a, k) => a + S.plan.objects[k].x, 0) / idx.length;
  const cy = idx.reduce((a, k) => a + S.plan.objects[k].y, 0) / idx.length;
  const rad = deg * Math.PI / 180, c = Math.cos(rad), s = Math.sin(rad);
  for (const k of idx) {
    const o = S.plan.objects[k];
    if (idx.length > 1) { const dx = o.x - cx, dy = o.y - cy; o.x = r4(cx + dx * c - dy * s); o.y = r4(cy + dx * s + dy * c); }
    o.facing = r2((((o.facing + deg) % 360) + 360) % 360);
  }
  redrawAll();
}

function nudge(dx, dy) {
  if (S.sel === null && S.spotSel !== null) {
    const sp = S.plan.camp_event.spots[S.spotSel];
    pushHistory(); sp.x = r2(sp.x + dx); sp.y = r2(sp.y + dy); redrawAll(); return;
  }
  if (S.sel === null) return;
  pushHistory();
  for (const k of (S.plan.objects[S.sel]._stamp && S._stampMode ? stampIndices(S.sel) : [S.sel])) {
    S.plan.objects[k].x = r4(S.plan.objects[k].x + dx); S.plan.objects[k].y = r4(S.plan.objects[k].y + dy);
  }
  redrawAll();
}

// ----------------------------------------------------------- panels: left
const areaBox = h('div', {});
const planBox = h('div', {});
const tabsBox = h('div', {});
put(left, areaBox, planBox, tabsBox);

function renderArea() {
  clear(areaBox);
  put(areaBox, h('h2', {}, 'Area'));
  if (S.areaInfo) {
    const a = S.areaInfo;
    put(areaBox, h('div', { class: 'card' },
      h('div', { class: 'row' }, h('b', {}, a.name || a.resref), h('button', { class: 'small right', onclick: () => { S.areaInfo = null; renderArea(); } }, 'change')),
      h('div', { class: 'mono muted small' }, `${a.resref} · ${a.width * 10}×${a.height * 10} m · ${a.tileset}`),
      h('div', { class: 'row', style: { marginTop: '6px' } },
        h('span', { class: 'chip' }, a.interior ? 'interior' : 'exterior'), a.underground ? h('span', { class: 'chip' }, 'underground') : null,
        h('span', { class: `chip ${a.cr ? '' : 'warn'}` }, a.cr ? `cr ${a.cr}` : 'no cr set'),
        h('span', { class: 'chip' }, `${a.counts.creatures || 0} creatures · ${a.counts.placeables || 0} props`)),
      a.groups.length ? h('div', { class: 'small muted', style: { marginTop: '6px' } }, 'Existing groups: ' +
        a.groups.map(g => `r${g.n} ${g.ute}×${g.spawns}`).join(', ')) : null,
      a.plans && a.plans.length ? h('div', { class: 'small', style: { marginTop: '6px' } }, 'Studio plans here: ',
        a.plans.map(p => savedPlans.some(sp => sp.id === p) ? h('span', { class: 'chip click', onclick: () => loadPlan(p) }, p) : h('span', { class: 'chip' }, p))) : null));
    return;
  }
  const list = searchList({
    items: () => areas, placeholder: `Search ${areas.length} areas by name or resref…`,
    filter: (a, q) => !q || (a.resref + ' ' + (a.name || '')).toLowerCase().includes(q),
    render: a => h('div', {}, h('b', {}, a.name || a.resref), h('span', { class: 'mono muted small' }, ` ${a.resref}`),
      h('span', { class: 'sub' }, `${a.width}×${a.height} · cr ${a.cr ?? '–'}`)),
    onPick: a => chooseArea(a.resref),
  });
  put(areaBox, list.el);
}

async function chooseArea(resref, keepPlan = false) {
  if (!keepPlan && S.plan.objects.length && S.plan.area !== resref) {
    const ok = await modal('Discard current plan?', h('p', {}, `The current plan has ${S.plan.objects.length} object(s) in ${S.plan.area}. Changing area discards them.`),
      [{ label: 'Cancel', value: false }, { label: 'Discard', value: true, danger: true }]);
    if (!ok) return;
  }
  try {
    const [detail] = await Promise.all([api(`/api/areas/${resref}`)]);
    S.detail = detail;
    S.areaInfo = areas.find(a => a.resref === resref) || detail;
    S.walk = null;
    try { S.walk = await api(`/api/areas/${resref}/walk`); } catch (e) { /* walk data is optional */ }
    map.setWalk(S.walk);
    if (!keepPlan) { const t = S.plan.title, id = S.plan.id; S.plan = newPlan(); S.plan.title = t; S.plan.id = id; S.history = []; }
    S.plan.area = resref;
    S.sel = null;
    map.hidePlan = S.plan.id;
    map.setArea(detail);
    location.hash = `area=${resref}`;
    redrawAll();
  } catch (e) { toast(e.message, 'error'); }
}

function renderPlan() {
  clear(planBox);
  const title = h('input', { type: 'text', value: S.plan.title, placeholder: 'e.g. Wolf den in Mantle Clearing', style: { width: '100%' },
    oninput: e => { S.plan.title = e.target.value; if (!S.idTouched) { S.plan.id = slug(e.target.value); idIn.value = S.plan.id; map.hidePlan = S.plan.id; map.render(); } renderStage(); eventInfoSoon(); } });
  const idIn = h('input', { type: 'text', value: S.plan.id, placeholder: 'plan id (a-z 0-9 _)', style: { width: '100%' },
    oninput: e => { S.idTouched = true; S.plan.id = e.target.value.trim(); map.hidePlan = S.plan.id; map.render(); renderStage(); eventInfoSoon(); } });
  const crIn = h('input', { type: 'number', min: 1, max: 40, value: S.plan.cr ?? '', placeholder: S.areaInfo && S.areaInfo.cr ? String(S.areaInfo.cr) : 'cr',
    oninput: e => { S.plan.cr = e.target.value === '' ? null : Number(e.target.value); renderStage(); } });
  const savedSel = h('select', { onchange: e => { if (e.target.value) loadPlan(e.target.value); e.target.value = ''; } },
    h('option', { value: '' }, `Load saved plan… (${savedPlans.length})`), savedPlans.map(p => h('option', { value: p.id }, `${p.title} (${p.area || '?'})`)));
  put(planBox, h('h2', { style: { marginTop: '14px' } }, 'Camp plan'),
    h('div', { class: 'field' }, h('label', {}, 'Title'), title),
    h('div', { class: 'grid2' },
      h('div', { class: 'field' }, h('label', {}, 'Plan id (re-staging replaces its objects)'), idIn),
      h('div', { class: 'field' }, h('label', {}, 'Area cr (required for spawns/loot)'), crIn)),
    h('div', { class: 'row' }, savedSel, h('button', { class: 'small', onclick: savePlan }, 'Save plan'),
      h('button', { class: 'small', onclick: () => newBlank() }, 'New')));
}

async function newBlank() {
  if (S.plan.objects.length && !(await modal('Start a new plan?', h('p', {}, 'Unsaved objects in the current plan will be lost.'),
    [{ label: 'Cancel', value: false }, { label: 'New plan', value: true, danger: true }]))) return;
  const area = S.plan.area;
  S.plan = newPlan(); S.plan.area = area; S.history = []; S.sel = null; S.spotSel = null; S.eventInfo = null; S.eventError = ''; S.idTouched = false; map.hidePlan = '';
  redrawAll();
}

async function savePlan() {
  if (!/^[a-z0-9_]{1,32}$/.test(S.plan.id)) { toast('Give the plan a title/id first (a-z 0-9 _)', 'warn'); return; }
  try {
    const r = await api('/api/specs/camps', { method: 'POST', body: { spec: cleanPlan() } });
    S.dirty = false;
    toast(`Saved plan ${r.id} (specs/camps/${r.id}.json)`, 'good');
    const i = savedPlans.findIndex(p => p.id === r.id);
    const rec = { id: r.id, title: S.plan.title || r.id, area: S.plan.area };
    if (i >= 0) savedPlans[i] = rec; else savedPlans.push(rec);
    renderPlan();
  } catch (e) { toast(e.message, 'error'); }
}

async function loadPlan(id) {
  try {
    const plan = await api(`/api/specs/camps/${id}`);
    S.plan = Object.assign(newPlan(), plan);
    S.plan.objects = (plan.objects || []).map(o => Object.assign({ z: null }, o));
    S.plan.camp_event = plan.camp_event && Object.keys(plan.camp_event).length ? Object.assign(newCampEvent(), plan.camp_event) : null;
    S.spotSel = null; S.eventInfo = null; S.eventError = '';
    S.idTouched = true; S.history = [];
    await chooseArea(plan.area, true);
    toast(`Loaded plan ${id}`, 'good');
  } catch (e) { toast(e.message, 'error'); }
}

// tabs ---------------------------------------------------------------------
let tab = 'prefabs';
const propFilter = { kind: 'all' };
const creatureFilter = { kind: 'all' };

function renderTabs() {
  clear(tabsBox);
  const names = [['prefabs', 'Prefabs'], ['props', 'Props'], ['creatures', 'Creatures'], ['markers', 'Spawns'], ['waypoints', 'Waypoints']];
  put(tabsBox, h('h2', { style: { marginTop: '14px' } }, 'Place'),
    h('div', { class: 'tabs' }, names.map(([k, label]) => h('button', { class: k === tab ? 'active' : '', onclick: () => { tab = k; renderTabs(); } }, label))));
  if (tab === 'prefabs') put(tabsBox, prefabTab());
  else if (tab === 'props') put(tabsBox, propsTab());
  else if (tab === 'creatures') put(tabsBox, creaturesTab());
  else if (tab === 'markers') put(tabsBox, markersTab());
  else put(tabsBox, waypointsTab());
}

/** Nearest spot to the view centre where a square of side 2r+1 m is >= 97% walkable (summed-area table). */
function openSpot(radius) {
  const w = S.walk;
  if (!w || !w.available) return null;
  const W = w.width, H = w.height, r = Math.ceil(radius), stride = W + 1;
  const sat = new Int32Array(stride * (H + 1));
  for (let y = 0; y < H; y++) {
    const row = w.rows[y];
    for (let x = 0; x < W; x++) {
      sat[(y + 1) * stride + x + 1] = (row.charCodeAt(x) === 49 ? 1 : 0) + sat[y * stride + x + 1] + sat[(y + 1) * stride + x] - sat[y * stride + x];
    }
  }
  const [cx, cy] = map.toWorld(map.cw / 2, map.ch / 2);
  const area = (2 * r + 1) ** 2;
  let best = null;
  for (let y = r; y < H - r; y++) {
    for (let x = r; x < W - r; x++) {
      const x0 = x - r, y0 = y - r, x1 = x + r + 1, y1 = y + r + 1;
      const sum = sat[y1 * stride + x1] - sat[y0 * stride + x1] - sat[y1 * stride + x0] + sat[y0 * stride + x0];
      if (sum / area < 0.97) continue;
      const d = Math.hypot(x + 0.5 - cx, y + 0.5 - cy);
      if (!best || d < best.d) best = { x: x + 0.5, y: y + 0.5, d };
    }
  }
  return best;
}

function prefabTab() {
  const box = h('div', {});
  const gm = h('div', {});
  const spotBox = h('div', {});
  const drawMap = () => {
    clear(gm);
    if (S.tool.type !== 'prefab') return;
    const pf = prefabs.find(p => p.id === S.tool.id);
    const used = [...new Set(pf.items.filter(i => i.kind === 'marker').map(i => i.group))];
    if (!used.length) return;
    put(gm, h('div', { class: 'card', style: { marginTop: '8px' } }, h('b', {}, 'Spawn marker groups in this prefab'),
      h('p', { class: 'muted small' }, 'Markers add spawn points for an area group. Map each prefab group to a group number; pick an unused one for a dedicated camp group.'),
      used.map(g => h('div', { class: 'row', style: { marginBottom: '4px' } }, h('span', {}, `prefab group ${g} →`),
        h('select', { onchange: e => { S.gmap[g] = Number(e.target.value); } },
          [1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => h('option', { value: n, selected: (S.gmap[g] ?? g) === n }, `group ${n}${groupLabel(n)}`)))))));
  };
  put(box, h('div', { class: 'list', style: { maxHeight: '330px' } }, prefabs.map(pf => h('div', {
    class: `item${S.tool.type === 'prefab' && S.tool.id === pf.id ? ' sel' : ''}`,
    onclick: () => {
      const used = [...new Set(pf.items.filter(i => i.kind === 'marker').map(i => i.group))];
      S.gmap = {};
      for (const g of used) S.gmap[g] = freeGroup([...Object.values(S.gmap)]);
      setTool({ type: 'prefab', id: pf.id });
    } },
    h('div', {}, h('b', {}, pf.name), h('div', { class: 'muted small' }, pf.description)),
    h('span', { class: 'sub' }, `${pf.items.length}`)))), gm,
    spotBox,
    h('p', { class: 'muted small' }, 'Click the map to stamp. R / Shift+R rotates; Esc cancels. Stamped props can be moved individually.'));
  drawMap();
  if (S.tool.type === 'prefab' && S.walk && S.walk.available) {
    const pf = prefabs.find(p => p.id === S.tool.id);
    put(spotBox, h('div', { class: 'card', style: { marginTop: '8px' } },
      h('div', { class: 'row' }, h('button', { class: 'small', onclick: () => {
        clear(spotBox);
        const best = openSpot(pf.radius + 1);
        if (!best) { put(spotBox, h('div', { class: 'issue warning' }, `No open ground big enough for "${pf.name}" in this area.`)); return; }
        map.centerOn(best.x, best.y);
        S.spotRotation = S.rotation;
        put(spotBox, h('div', { class: 'card', style: { marginTop: '8px' } },
          h('div', { class: 'small' }, `Open ground found at (${best.x.toFixed(1)}, ${best.y.toFixed(1)}), ${best.d.toFixed(0)} m from the view centre.`),
          h('button', { class: 'small primary', style: { marginTop: '6px' }, onclick: () => { place(best.x, best.y); clear(spotBox); } }, `Stamp "${pf.name}" here`)));
      } }, 'Find open ground'), h('span', { class: 'muted small' }, 'nearest spot where the whole footprint is walkable'))));
  }
  return box;
}

function groupLabel(n) {
  const p = S.plan.groups.find(g => g.n === n);
  if (p && p.ute) return ` — plan: ${p.ute}`;
  const a = (S.areaInfo && S.areaInfo.groups || []).find(g => g.n === n);
  return a ? ` — area: ${a.ute}` : ' — unused';
}

function freeGroup(taken = []) {
  for (let n = 1; n <= 9; n++) {
    if (taken.includes(n)) continue;
    if (S.plan.groups.some(g => g.n === n)) continue;
    if ((S.areaInfo && S.areaInfo.groups || []).some(g => g.n === n)) continue;
    return n;
  }
  return 1;
}

function propsTab() {
  const kinds = ['all', 'decor', 'container', 'light', 'usable', 'respawning'];
  const box = h('div', {});
  put(box, h('div', { class: 'row', style: { marginBottom: '6px' } }, kinds.map(k =>
    h('span', { class: `chip click ${propFilter.kind === k ? 'sel' : ''}`, onclick: () => { propFilter.kind = k; renderTabs(); } }, k))));
  const list = searchList({
    items: () => palette, placeholder: `Search ${palette.length} props (bed, tent, barrel, fire…)`,
    filter: (p, q) => (propFilter.kind === 'all' || p.kind === propFilter.kind) && (!q || (p.resref + ' ' + p.name).toLowerCase().includes(q)),
    render: p => h('div', {}, h('b', {}, p.resref), p.name ? h('span', { class: 'muted small' }, ` ${p.name}`) : null,
      h('span', { class: 'sub' }, `${p.kind} · ×${p.count}`)),
    onPick: p => { setTool({ type: 'placeable', resref: p.resref }); if (p.kind === 'container') toast('Containers roll TFN loot (treas_*): place them deliberately', 'warn', 6000); },
  });
  put(box, list.el, h('p', { class: 'muted small' }, 'Palette = every placeable TFN already uses, so instances are known-good. "respawning" (plx_) props come back every area refresh.'));
  return box;
}

function creaturesTab() {
  const kinds = ['all', 'monster', 'npc', 'other', 'henchman', 'base'];
  const box = h('div', {});
  put(box, h('div', { class: 'row', style: { marginBottom: '6px' } }, kinds.map(k =>
    h('span', { class: `chip click ${creatureFilter.kind === k ? 'sel' : ''}`, title: k === 'base' ? 'base-game creatures that TFN areas already place' : '', onclick: () => { creatureFilter.kind = k; renderTabs(); } }, k === 'base' ? 'base-game' : k))));
  const list = searchList({
    items: () => creatures.filter(c => c.kind !== 'marker'), placeholder: 'Search creatures…',
    filter: (c, q) => (creatureFilter.kind === 'all' || c.kind === creatureFilter.kind) && (!q || (c.resref + ' ' + c.name).toLowerCase().includes(q)),
    render: c => h('div', {}, h('b', {}, c.name || c.resref), h('span', { class: 'mono muted small' }, ` ${c.resref}`), h('span', { class: 'sub' }, `CR ${fmtNum(c.cr)} · ${c.kind}`)),
    onPick: c => setTool({ type: 'creature', resref: c.resref }),
  });
  put(box, list.el, h('p', { class: 'muted small' }, 'Hand-placed creatures are recorded by area_init and respawn at this exact spot on every refresh. Use Spawn markers for roaming groups.'));
  return box;
}

function markersTab() {
  const box = h('div', {});
  put(box, h('p', { class: 'muted small' }, 'A marker is an invisible spawn point for group N. area_init reads each marker\'s position and removes it; group N\'s encounter is spread over all its markers.'));
  for (let n = 1; n <= 9; n++) {
    put(box, h('div', { class: `item row${S.tool.type === 'marker' && S.tool.group === n ? ' sel' : ''}`,
      style: { cursor: 'pointer', padding: '5px 8px', border: '1px solid var(--line)', borderRadius: '6px', marginBottom: '4px' },
      onclick: () => setTool({ type: 'marker', group: n }) },
      h('b', {}, `Group ${n}`), h('span', { class: 'muted small' }, groupLabel(n).replace(/^ — /, '')),
      h('span', { class: 'chip right' }, `${S.plan.objects.filter(o => o.kind === 'marker' && o.group === n).length} in plan`)));
  }
  return box;
}

function waypointsTab() {
  return h('div', {},
    h('div', { class: `item row${S.tool.type === 'waypoint' ? ' sel' : ''}`, style: { cursor: 'pointer', padding: '6px 8px', border: '1px solid var(--line)', borderRadius: '6px' },
      onclick: () => setTool({ type: 'waypoint', resref: '_wp_event' }) }, h('b', {}, 'Event waypoint'), h('span', { class: 'mono muted small' }, '_wp_event')),
    h('p', { class: 'muted small' }, 'On each refresh there is an event_chance% roll; on success one event script (event1…event9 on the area) runs with a random event waypoint as OBJECT_SELF. Configure scripts under Events on the right.'));
}

// ----------------------------------------------------------- panels: right
const groupsBox = h('div', {});
const eventsBox = h('div', {});
const campBox = h('div', { id: 'camp-box' });
const campInfoBox = h('div', {});
const selBox = h('div', {});
const stageBox = h('div', {});
const problemsBox = h('div', {});
const resultBox = h('div', {});
put(stageBox, h('h2', { style: { marginTop: '14px' } }, 'Stage'), problemsBox, resultBox);
put(right, groupsBox, eventsBox, campBox, selBox, stageBox);

// ------------------------------------------------------------ random camp
const templateObjects = () => S.plan.objects.filter(o => o.kind === 'placeable' || o.kind === 'creature');
const footprint = (objs, o) => objs.reduce((m, t) => Math.max(m, Math.hypot(t.x - o.x, t.y - o.y)), 0);

/** The camp's pivot: the one the user set, else the centre of its objects (what the server uses too). */
function effOrigin() {
  const ce = S.plan.camp_event;
  if (!ce) return null;
  if (ce.origin) return ce.origin;
  const t = templateObjects();
  if (!t.length) return null;
  return { x: r4(t.reduce((a, o) => a + o.x, 0) / t.length), y: r4(t.reduce((a, o) => a + o.y, 0) / t.length), facing: 90 };
}

function syncCamp() {
  const ce = S.plan.camp_event, o = effOrigin();
  const t = templateObjects();
  map.setCamp(ce ? { origin: o, spots: ce.spots, template: t, sel: S.spotSel ?? -1, radius: o ? footprint(t, o) : 0,
                     designBuilt: !!ce.include_origin || !ce.spots.length } : null);
}

let infoTimer = 0, infoSeq = 0;
function eventInfoSoon(delay = 300) { clearTimeout(infoTimer); infoTimer = setTimeout(refreshEventInfo, delay); }

async function refreshEventInfo() {
  const ce = S.plan.camp_event;
  if (!ce || !S.detail || !/^[a-z0-9_]{1,32}$/.test(S.plan.id)) { S.eventInfo = null; S.eventError = ''; renderCampInfo(); renderStage(); return; }
  const seq = ++infoSeq;
  try {
    const info = await api('/api/camps/event-info', { method: 'POST', body: { plan: cleanPlan() } });
    if (seq !== infoSeq) return;
    S.eventInfo = info; S.eventError = '';
  } catch (e) {
    if (seq !== infoSeq) return;
    S.eventInfo = null; S.eventError = e.message;
  }
  renderCampInfo(); renderStage();
}

function afterCampEdit() { S.dirty = true; syncCamp(); eventInfoSoon(); renderStage(); }

function setCampEvent(on) {
  pushHistory();
  S.plan.camp_event = on ? newCampEvent() : null;
  S.spotSel = null;
  if (S.tool.type === 'spot' || S.tool.type === 'pivot') setTool({ type: 'select' });
  redrawAll();
}

function selectSpot(i) {
  S.spotSel = i; S.sel = null;
  map.setSelected([]); renderSelection(); syncCamp(); highlightSpotRow();
}
function highlightSpotRow() { $$('.spot-row', campBox).forEach(el => el.classList.toggle('sel', Number(el.dataset.i) === S.spotSel)); }

function addSpot(x, y) {
  const ce = S.plan.camp_event;
  if (!ce) { toast('Turn on "Random camp" first', 'warn'); return; }
  if (!map.inBounds(x, y, 0.5)) { toast('That is outside the area', 'warn'); return; }
  if (ce.spots.length >= MAX_SPOTS) { toast(`At most ${MAX_SPOTS} spots per camp`, 'warn'); return; }
  pushHistory();
  ce.spots.push({ x: r2(x), y: r2(y), facing: ((S.rotation % 360) + 360) % 360 });
  S.spotSel = ce.spots.length - 1; S.sel = null;
  redrawAll();
}

function setPivot(x, y) {
  const ce = S.plan.camp_event;
  if (!ce) return;
  pushHistory();
  ce.origin = { x: r2(x), y: r2(y), facing: (effOrigin() || { facing: 90 }).facing };
  setTool({ type: 'select' });
  redrawAll();
}

function removeSpot(i) {
  const ce = S.plan.camp_event;
  if (!ce || !ce.spots[i]) return;
  pushHistory();
  ce.spots.splice(i, 1);
  S.spotSel = null;
  redrawAll();
}

function rotateSpot(i, deg) {
  const sp = S.plan.camp_event.spots[i];
  pushHistory();
  sp.facing = r2((((sp.facing + deg) % 360) + 360) % 360);
  redrawAll();
}

function moveSpot(i, x, y, final) {
  const sp = S.plan.camp_event && S.plan.camp_event.spots[i];
  if (!sp) return;
  if (!S._movingSpot) { pushHistory(); S._movingSpot = true; }
  sp.x = r2(x); sp.y = r2(y);
  if (final) S._movingSpot = false;
  syncCamp();
  if (final) { renderCamp(); eventInfoSoon(); }
}

function addSpots(list) {
  const ce = S.plan.camp_event;
  let added = 0;
  for (const sp of list) {
    if (ce.spots.length >= MAX_SPOTS) break;
    if (ce.spots.some(o => Math.hypot(o.x - sp.x, o.y - sp.y) < 1)) continue;
    ce.spots.push({ x: r2(sp.x), y: r2(sp.y), facing: ((sp.facing % 360) + 360) % 360 });
    added++;
  }
  return added;
}

async function suggestSpots(count) {
  try {
    const r = await api('/api/camps/suggest-spots', { method: 'POST', body: { plan: cleanPlan(), count, seed: `${S.plan.id}:${S.seed++}` } });
    if (!r.spots.length) { toast(`No open ground found where this camp (about ${(r.footprint * 2).toFixed(0)} m across) fits`, 'warn', 7000); return; }
    pushHistory();
    const n = addSpots(r.spots);
    S.spotSel = S.plan.camp_event.spots.length - 1;
    redrawAll();
    toast(n ? `Added ${n} suggested spot(s): open ground where the whole camp fits` : 'Those spots are already in the list', n ? 'good' : 'info');
  } catch (e) { toast(e.message, 'error', 7000); }
}

function importSpots() {
  const found = (S.eventInfo && S.eventInfo.waypoint_spots) || [];
  pushHistory();
  const n = addSpots(found);
  if (!n) { S.history.pop(); toast('Nothing new to import', 'info'); return; }
  redrawAll();
  toast(`Imported ${n} marker(s) as spots`, 'good');
}

function groupChoices() {
  const ns = new Set([...((S.areaInfo && S.areaInfo.groups) || []).map(g => g.n), ...S.plan.groups.filter(g => g.ute).map(g => g.n)]);
  return [...ns].sort((a, b) => a - b);
}

function renderCamp() {
  clear(campBox);
  const ce = S.plan.camp_event;
  put(campBox, h('h2', { style: { marginTop: '14px' } }, 'Random camp'),
    h('label', { class: 'row', style: { margin: 0, color: 'var(--text)', gap: '6px', flexWrap: 'nowrap' } },
      h('input', { type: 'checkbox', id: 'camp-event-on', checked: !!ce, onchange: e => setCampEvent(e.target.checked) }),
      'Build this camp only sometimes, at a random spot'));
  if (!ce) {
    put(campBox, h('p', { class: 'muted small' }, 'Off: the props and creatures of this plan are placed in the area for good. On: they become a template — the area builds the camp ' +
      'only now and then when it refreshes, at one of the spots you choose, turned to face the way you set. Nothing of it is stored in the area file.'), campInfoBox);
    return;
  }
  const o = effOrigin();
  const spotRows = ce.spots.map((sp, i) => {
    const num = (key, step, w) => h('input', { type: 'number', step, value: sp[key], 'aria-label': `spot ${i + 1} ${key}`, style: { width: w },
      oninput: e => { const v = Number(e.target.value); if (e.target.value !== '' && Number.isFinite(v)) { sp[key] = key === 'facing' ? ((v % 360) + 360) % 360 : v; afterCampEdit(); } },
      onfocus: () => { if (S.spotSel !== i) selectSpot(i); } });
    return h('div', { class: `spot-row${S.spotSel === i ? ' sel' : ''}`, 'data-i': i },
      h('button', { class: 'small', title: 'show on the map', onclick: () => { selectSpot(i); map.centerOn(sp.x, sp.y); } }, `#${i + 1}`),
      h('label', {}, 'x'), num('x', 0.5, '62px'), h('label', {}, 'y'), num('y', 0.5, '62px'), h('label', {}, '°'), num('facing', 15, '58px'),
      h('button', { class: 'small', title: 'turn left 45°', onclick: () => rotateSpot(i, 45) }, '⟲'),
      h('button', { class: 'small', title: 'turn right 45°', onclick: () => rotateSpot(i, -45) }, '⟳'),
      h('button', { class: 'small danger', title: 'remove this spot', onclick: () => removeSpot(i) }, '✕'));
  });
  const groups = groupChoices();
  const found = (S.eventInfo && S.eventInfo.waypoint_spots) || [];
  const walkOk = !!(S.walk && S.walk.available);
  const countIn = h('input', { type: 'number', min: 1, max: MAX_SPOTS, value: 4, style: { width: '52px' }, id: 'camp-suggest-count' });
  put(campBox,
    h('div', { class: 'card' },
      h('p', { class: 'muted small', style: { marginTop: 0 } }, 'Props and creatures you place are the camp. Add spots below: when the area refreshes the camp may appear at one of them, turned to the spot\'s facing ' +
        '(0 = east, 90 = north). The camp is drawn facing north (90°) where you design it.'),
      h('div', { class: 'grid2' },
        h('div', { class: 'field' }, h('label', {}, 'Event script (generated)'), h('input', { type: 'text', id: 'camp-script', value: ce.script, placeholder: (S.eventInfo && S.eventInfo.script) || 'eve_<plan id>', style: { width: '100%' },
          oninput: e => { ce.script = e.target.value.trim().toLowerCase(); afterCampEdit(); } })),
        h('div', { class: 'field' }, h('label', { title: 'Each slot is one more entry in the area\'s event list: more slots, more often' }, 'Event slots (more = more often)'),
          h('select', { id: 'camp-weight', onchange: e => { ce.weight = Number(e.target.value); afterCampEdit(); } },
            [1, 2, 3, 4].map(n => h('option', { value: n, selected: ce.weight === n }, String(n)))))),
      h('div', { class: 'row', style: { margin: '6px 0' } }, h('b', {}, 'Pivot'),
        o ? h('span', { class: 'mono small' }, `(${o.x.toFixed(1)}, ${o.y.toFixed(1)}) facing ${o.facing}°`) : h('span', { class: 'muted small' }, 'place something first'),
        ce.origin ? h('span', { class: 'chip' }, 'custom') : h('span', { class: 'chip' }, 'centre of the camp'),
        h('button', { class: 'small', id: 'camp-set-pivot', disabled: !o, onclick: () => setTool({ type: 'pivot' }) }, 'Set…'),
        ce.origin ? h('button', { class: 'small', onclick: () => { pushHistory(); ce.origin = null; redrawAll(); } }, 'Reset') : null),
      h('label', { class: 'row', style: { margin: '2px 0 6px', color: 'var(--text)', gap: '6px', flexWrap: 'nowrap' } },
        h('input', { type: 'checkbox', id: 'camp-include-origin', checked: !!ce.include_origin, onchange: e => { ce.include_origin = e.target.checked; redrawAll(); } }),
        'Also build it where it is designed now'),
      h('div', { class: 'row', style: { marginBottom: '4px' } }, h('b', {}, `Spots (${ce.spots.length}/${MAX_SPOTS})`),
        h('button', { class: 'small', id: 'camp-add-spot', onclick: () => { if (!o) { toast('Place at least one prop or creature first', 'warn'); return; } setTool({ type: 'spot' }); } }, '+ Spot (click map)')),
      ...spotRows,
      !ce.spots.length ? h('div', { class: 'muted small' }, 'No spots yet: the camp would be built at its design location only.') : null,
      h('div', { class: 'row', style: { marginTop: '6px' } },
        h('button', { class: 'small', id: 'camp-suggest', disabled: !walkOk || !o, title: walkOk ? 'find open ground where the whole camp fits' : 'needs the NWN game data (walkmesh)',
          onclick: () => suggestSpots(Math.max(1, Math.min(MAX_SPOTS, Number(countIn.value) || 4))) }, 'Suggest'), countIn, h('span', { class: 'muted small' }, 'spots on open ground'),
        h('button', { class: 'small', id: 'camp-import', disabled: !found.length, title: 'event waypoints (_wp_event) and waypoints tagged camp_spot… that are already in the area',
          onclick: importSpots }, `Import markers (${found.length})`)),
      h('div', { class: 'row', style: { marginTop: '10px' } }, h('b', {}, 'Replaces'),
        h('select', { id: 'camp-replaces', onchange: e => { ce.replaces_group = e.target.value ? Number(e.target.value) : null; redrawAll(); } },
          h('option', { value: '' }, 'no spawn group (adds to the area)'), groups.map(n => h('option', { value: n, selected: ce.replaces_group === n }, `group random${n}`))),
        ce.replaces_group ? [h('label', { style: { margin: 0 } }, 'within'),
          h('input', { type: 'number', min: 0, max: 300, value: ce.replace_radius || 0, id: 'camp-radius', style: { width: '62px' },
            oninput: e => { ce.replace_radius = Number(e.target.value) || 0; afterCampEdit(); } }), h('span', { class: 'muted small' }, 'm (0 = all)')] : null),
      ce.replaces_group ? h('div', { class: 'muted small' }, 'While the camp stands, that group\'s creatures are removed as they spawn (all of them, or only those near the camp).') : null),
    campInfoBox);
  renderCampInfo();
}

function renderCampInfo() {
  clear(campInfoBox);
  const ce = S.plan.camp_event;
  if (!ce) return;
  if (S.eventError) { put(campInfoBox, h('div', { class: 'issue error', id: 'camp-info' }, S.eventError)); return; }
  const info = S.eventInfo;
  if (!info) { put(campInfoBox, h('p', { class: 'muted small', id: 'camp-info' }, S.detail ? 'checking…' : 'choose an area')); return; }
  const scriptIn = document.getElementById('camp-script');
  if (scriptIn && info.script) scriptIn.placeholder = info.script;      // the name the server will use when this is left empty
  if (info.empty) { put(campInfoBox, h('div', { class: 'issue warning', id: 'camp-info' }, info.message)); return; }
  const w = info.wiring, pct = v => `${(v * 100).toFixed(1)}%`, n = info.variants.length;
  const lines = [
    `Script src/nss/${info.script}.nss (${info.script_state === 'new' ? 'new' : 'regenerated'}), event slot${w.slots.length > 1 ? 's' : ''} ${w.slots.map(i => 'event' + i).join(', ')}`,
    w.other_events.length ? `Shares the event roll with: ${w.other_events.join(', ')} (they become a little rarer)` : null,
    info.added_waypoint ? `Adds a _wp_event waypoint at (${info.added_waypoint.x.toFixed(1)}, ${info.added_waypoint.y.toFixed(1)}): events only run when the area has one` : null,
    w.gate ? `While the camp stands, group random${w.gate.group} loses ${w.gate.radius ? `its creatures within ${w.gate.radius} m` : 'all of its creatures'} (gate ${w.gate.script}${w.gate.chain ? `, chaining to ${w.gate.chain}` : ''})` : null,
    ...w.warnings,
  ].filter(Boolean);
  const problems = info.variants.flatMap(v => v.issues.filter(i => i.level === 'error' || i.level === 'warning'));
  put(campInfoBox, h('div', { class: 'card', id: 'camp-info' },
    h('div', { class: 'row' }, h('b', { id: 'camp-chance' }, `About ${pct(w.effective)} of area refreshes`), n > 1 ? h('span', { class: 'muted small' }, `· ~${pct(w.effective / n)} per spot`) : null),
    h('div', { class: 'muted small' }, `event_chance ${w.event_chance}%${w.chance_is_default ? ' (TFN default — this area sets none; change it under Events)' : ''} × ${w.slots.length} of ${w.slots_total} event slot(s)`),
    h('ul', { class: 'small', style: { paddingLeft: '16px', margin: '6px 0' } }, lines.map(l => h('li', {}, l))),
    problems.map(i => h('div', { class: `issue ${i.level}` }, i.message))));
}

function renderGroups() {
  clear(groupsBox);
  put(groupsBox, h('h2', {}, 'Spawn groups'));
  const rows = S.plan.groups.map((g, i) => {
    const uteSel = h('select', { style: { flex: 1, minWidth: 0 }, onchange: e => { pushHistory(); g.ute = e.target.value; renderGroups(); renderTabs(); renderStage(); } },
      h('option', { value: '' }, '(choose encounter)'), uteNames().map(u => h('option', { value: u, selected: g.ute === u }, u)));
    const info = utes.find(u => u.resref === g.ute);
    return h('div', { class: 'card', style: { padding: '8px', marginBottom: '6px' } },
      h('div', { class: 'row', style: { flexWrap: 'nowrap' } },
        h('select', { style: { width: '104px', flex: 'none' }, onchange: e => { g.n = Number(e.target.value); renderTabs(); renderGroups(); renderStage(); } }, [1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => h('option', { value: n, selected: g.n === n }, `random${n}`))),
        uteSel, h('button', { class: 'small danger', style: { flex: 'none' }, onclick: () => { pushHistory(); S.plan.groups.splice(i, 1); redrawAll(); } }, '✕')),
      h('div', { class: 'row', style: { marginTop: '6px' } },
        h('label', { style: { margin: 0 } }, 'spawns'), h('input', { type: 'number', min: 1, max: 200, value: g.spawns, oninput: e => { g.spawns = Number(e.target.value) || 1; } }),
        h('label', { style: { margin: 0 } }, 'script'), h('input', { type: 'text', value: g.script || '', placeholder: 'optional', style: { width: '110px' }, oninput: e => { g.script = e.target.value.trim(); } })),
      info ? h('div', { class: 'muted small', style: { marginTop: '4px' } }, `${info.creatures.length} creatures · ${info.unique_chance}% unique${info.rare ? ' · rare ' + info.rare : ''}`) : null,
      !g.ute ? h('div', { class: 'issue warning' }, 'pick an encounter blueprint') : null,
      !S.plan.objects.some(o => o.kind === 'marker' && o.group === g.n) ? h('div', { class: 'issue warning' }, `no random${g.n} markers in the plan — group will not spawn`) : null);
  });
  put(groupsBox, ...rows, h('div', { class: 'row' },
    h('button', { class: 'small', onclick: () => { pushHistory(); S.plan.groups.push({ n: freeGroup(), ute: '', spawns: 6, script: '' }); redrawAll(); } }, '+ group'),
    h('button', { class: 'small', onclick: newEncounter }, '+ new encounter…')),
    S.plan.new_utes.length ? h('div', { class: 'muted small', style: { marginTop: '6px' } }, 'New encounters in this plan: ' +
      S.plan.new_utes.map(u => u.resref).join(', ')) : null,
    h('p', { class: 'muted small' }, 'Only groups you list here are changed; other area groups keep their current encounter.'));
}

async function newEncounter() {
  const holder = h('div', {});
  const ed = createUteEditor({ creatures, areas, spec: blankSpec(), existing: new Set(utes.map(u => u.resref)), onChange: () => {} });
  put(holder, ed.el);
  const ok = await modal('New encounter blueprint', holder, [{ label: 'Cancel', value: false }, { label: 'Add to plan', value: true, primary: true }]);
  if (!ok) return;
  const spec = ed.getSpec();
  if (!/^[a-z0-9_]{1,16}$/.test(spec.resref) || !spec.creatures.length) { toast('Encounter needs a valid resref and at least one creature', 'error'); return; }
  pushHistory();
  S.plan.new_utes = S.plan.new_utes.filter(u => u.resref !== spec.resref).concat([spec]);
  const free = S.plan.groups.find(g => !g.ute);
  if (free) free.ute = spec.resref; else S.plan.groups.push({ n: freeGroup(), ute: spec.resref, spawns: 6, script: '' });
  redrawAll();
}

function renderEvents() {
  clear(eventsBox);
  put(eventsBox, h('h2', { style: { marginTop: '14px' } }, 'Events'));
  S.plan.events.forEach((e, i) => put(eventsBox, h('div', { class: 'row', style: { marginBottom: '4px' } },
    h('select', { onchange: ev => { e.n = Number(ev.target.value); eventInfoSoon(); } }, [1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => h('option', { value: n, selected: e.n === n }, `event${n}`))),
    h('input', { type: 'text', value: e.script, placeholder: 'script name', oninput: ev => { e.script = ev.target.value.trim(); eventInfoSoon(); }, style: { flex: 1 } }),
    h('button', { class: 'small danger', onclick: () => { S.plan.events.splice(i, 1); renderEvents(); eventInfoSoon(); } }, '✕'))));
  put(eventsBox, h('div', { class: 'row' }, h('button', { class: 'small', onclick: () => {
      const used = new Set(S.plan.events.map(e => e.n)); let n = 1; while (used.has(n) && n < 9) n++;
      S.plan.events.push({ n, script: '' }); renderEvents(); } }, '+ event script'),
    h('label', { style: { margin: 0 } }, 'event_chance %'),
    h('input', { type: 'number', min: 0, max: 100, value: S.plan.event_chance ?? '', placeholder: '50', oninput: e => { S.plan.event_chance = e.target.value === '' ? null : Number(e.target.value); eventInfoSoon(); } })));
}

function refreshSelection() {
  map.setSelected(S.sel === null ? [] : [S.sel]);
  renderSelection();
}

function renderSelection() {
  clear(selBox);
  const counts = {};
  for (const o of S.plan.objects) counts[o.kind] = (counts[o.kind] || 0) + 1;
  put(selBox, h('h2', { style: { marginTop: '14px' } }, 'Plan objects'),
    h('div', { class: 'row', style: { marginBottom: '6px' } },
      Object.entries(counts).map(([k, v]) => h('span', { class: 'chip', style: { borderColor: KIND_COLOR[k] } }, `${v} ${k}`)),
      !S.plan.objects.length ? h('span', { class: 'muted small' }, 'empty — pick something from the palette and click the map') : null));
  if (S.plan.camp_event && templateObjects().length) put(selBox, h('div', { class: 'muted small', style: { marginBottom: '6px' } },
    `${templateObjects().length} prop(s)/creature(s) form the random camp: they are kept in the generated script, not in the area file.`));
  if (S.plan.objects.length) put(selBox, h('div', { class: 'row', style: { marginBottom: '6px' } },
    h('button', { class: 'small', onclick: savePrefab }, 'Save as prefab…'),
    h('span', { class: 'muted small' }, S.sel !== null && S.plan.objects[S.sel] && S.plan.objects[S.sel]._stamp ? 'saves the selected stamp' : 'saves all plan objects')));
  const blocked = S.plan.objects.filter(o => map.blocked(o));
  if (blocked.length) put(selBox, h('div', { class: 'issue warning' },
    `${blocked.length} creature/marker/waypoint object(s) sit on non-walkable ground (red dashed ring on the map): they may be stuck or unreachable.`));
  const o = S.sel !== null ? S.plan.objects[S.sel] : null;
  if (!o) return;
  const num = (key, step = 0.5) => h('input', { type: 'number', step, value: o[key] ?? '', style: { width: '78px' },
    oninput: e => { o[key] = e.target.value === '' ? null : Number(e.target.value); map.setPlan(S.plan.objects); } });
  const stamped = !!o._stamp;
  put(selBox, h('div', { class: 'card' },
    h('div', { class: 'row' }, h('b', {}, o.kind === 'marker' ? `Spawn marker (group ${o.group})` : o.resref),
      o.kind !== 'marker' && creatureBy[o.resref] ? h('span', { class: 'chip' }, `CR ${fmtNum(creatureBy[o.resref].cr)}`) : null,
      h('button', { class: 'small danger right', onclick: removeSelected }, 'Delete')),
    h('div', { class: 'row', style: { marginTop: '8px' } }, h('label', { style: { margin: 0 } }, 'x'), num('x'), h('label', { style: { margin: 0 } }, 'y'), num('y')),
    h('div', { class: 'row', style: { marginTop: '6px' } }, h('label', { style: { margin: 0 } }, 'z'), h('input', { type: 'number', step: 0.1, value: o.z ?? '', placeholder: S.walk && S.walk.available ? 'auto (walkmesh)' : 'auto', style: { width: '104px' },
        oninput: e => { o.z = e.target.value === '' ? null : Number(e.target.value); } }),
      h('label', { style: { margin: 0 } }, 'facing'), num('facing', 15)),
    h('div', { class: 'row', style: { marginTop: '6px' } },
      h('button', { class: 'small', onclick: () => rotateSelected(-15) }, '⟲ 15°'), h('button', { class: 'small', onclick: () => rotateSelected(15) }, '⟳ 15°'),
      h('button', { class: 'small', onclick: () => { pushHistory(); const c = JSON.parse(JSON.stringify(o)); c.x = r4(c.x + 1); c.y = r4(c.y + 1); delete c._stamp; S.plan.objects.push(c); S.sel = S.plan.objects.length - 1; redrawAll(); } }, 'Duplicate')),
    o.kind === 'marker' ? h('div', { class: 'row', style: { marginTop: '6px' } }, h('label', { style: { margin: 0 } }, 'group'),
      h('select', { onchange: e => { pushHistory(); o.group = Number(e.target.value); ensureGroups([o.group]); redrawAll(); } },
        [1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => h('option', { value: n, selected: o.group === n }, String(n))))) : null,
    h('div', { class: 'field', style: { marginTop: '6px' } }, h('label', {}, 'tag (optional)'), h('input', { type: 'text', value: o.tag || '', style: { width: '100%' }, maxlength: 32,
      oninput: e => { o.tag = e.target.value.trim() || undefined; } })),
    stamped ? h('div', { class: 'row', style: { marginTop: '6px' } }, h('span', { class: 'muted small' }, `part of stamp #${o._stamp}:`),
      h('button', { class: 'small', onclick: () => { map.setSelected(stampIndices(S.sel)); } }, 'select all'),
      h('button', { class: 'small', onclick: () => rotateSelected(15, true) }, '⟳ stamp'),
      h('button', { class: 'small danger', onclick: () => { pushHistory(); const id = o._stamp; S.plan.objects = S.plan.objects.filter(p => p._stamp !== id); S.sel = null; redrawAll(); } }, 'delete stamp')) : null));
}

async function savePrefab() {
  const sel = S.sel !== null ? S.plan.objects[S.sel] : null;
  const objs = sel && sel._stamp ? S.plan.objects.filter(o => o._stamp === sel._stamp) : S.plan.objects;
  if (!objs.length) return;
  const cx = objs.reduce((a, o) => a + o.x, 0) / objs.length, cy = objs.reduce((a, o) => a + o.y, 0) / objs.length;
  const idIn = h('input', { type: 'text', placeholder: 'prefab id (a-z 0-9 _)', value: slug(S.plan.title || ''), style: { width: '100%' } });
  const nameIn = h('input', { type: 'text', placeholder: 'display name', value: S.plan.title || '', style: { width: '100%' } });
  const descIn = h('textarea', { rows: 2, placeholder: 'what is it for?' });
  const body = h('div', {}, h('p', { class: 'muted' }, `${objs.length} object(s) will be saved relative to their centre; markers keep their group numbers (remapped when stamped).`),
    h('div', { class: 'field' }, h('label', {}, 'Id'), idIn), h('div', { class: 'field' }, h('label', {}, 'Name'), nameIn), h('div', { class: 'field' }, h('label', {}, 'Description'), descIn));
  if (!(await modal('Save as prefab', body, [{ label: 'Cancel', value: false }, { label: 'Save', value: true, primary: true }]))) return;
  const prefab = {
    id: idIn.value.trim(), name: nameIn.value.trim() || idIn.value.trim(), description: descIn.value.trim(), tags: ['custom'],
    items: objs.map(o => {
      const it = { kind: o.kind, dx: r2(o.x - cx), dy: r2(o.y - cy), facing: r2(o.facing || 0) };
      if (o.kind === 'marker') it.group = o.group; else it.resref = o.resref;
      if (o.tag) it.tag = o.tag;
      return it;
    }),
  };
  try {
    await api('/api/prefabs', { method: 'POST', body: { prefab } });
    const fresh = await api('/api/prefabs');
    prefabs.length = 0; prefabs.push(...fresh);
    renderTabs();
    toast(`Saved prefab "${prefab.id}" (prefabs/${prefab.id}.json)`, 'good');
  } catch (e) { toast(e.message, 'error'); }
}

function cleanPlan() {
  const p = JSON.parse(JSON.stringify(S.plan));
  p.title = p.title || p.id;
  p.groups = p.groups.filter(g => g.ute);
  p.events = p.events.filter(e => e.script);
  if (p.camp_event) {
    const ce = p.camp_event;
    p.camp_event = { script: ce.script || undefined, weight: ce.weight || 1, origin: ce.origin || undefined, spots: ce.spots || [],
      include_origin: !!ce.include_origin, replaces_group: ce.replaces_group || undefined, replace_radius: ce.replace_radius || 0 };
  } else delete p.camp_event;
  return p;
}

function renderStage() {
  clear(problemsBox);
  const hard = [], soft = [];
  if (!S.detail) hard.push('choose an area');
  if (!/^[a-z0-9_]{1,32}$/.test(S.plan.id)) hard.push('plan needs a title/id (a-z 0-9 _)');
  if (S.plan.groups.some(g => !g.ute)) hard.push('a spawn group has no encounter');
  if (!S.plan.objects.length && !S.plan.groups.length) hard.push('nothing to stage yet');
  const markerGroups = [...new Set(S.plan.objects.filter(o => o.kind === 'marker').map(o => o.group))];
  for (const n of markerGroups) {
    const defined = S.plan.groups.some(g => g.n === n && g.ute) || (S.areaInfo && S.areaInfo.groups.some(g => g.n === n));
    if (!defined) soft.push(`markers for group ${n} but no encounter assigned to it (nothing will spawn there)`);
  }
  if (S.plan.groups.length && !S.plan.cr && !(S.areaInfo && S.areaInfo.cr)) soft.push('area has no cr variable: set one above (loot/XP/treasure maps need it)');
  if (S.plan.camp_event) {
    if (!templateObjects().length) hard.push('random camp: place at least one prop or creature (they are the camp)');
    else if (S.eventError) hard.push(`random camp: ${S.eventError}`);
    else if (S.eventInfo && S.eventInfo.errors && S.eventInfo.errors.length) {
      hard.push(`random camp: ${S.eventInfo.errors[0]}${S.eventInfo.errors.length > 1 ? ` (+${S.eventInfo.errors.length - 1} more)` : ''}`);
    }
  }
  put(problemsBox, hard.map(p => h('div', { class: 'issue error' }, p)), soft.map(p => h('div', { class: 'issue warning' }, p)),
    h('div', { class: 'row', style: { marginTop: '8px' } },
      h('button', { class: 'primary', disabled: hard.length > 0, onclick: () => stage(resultBox) }, 'Stage changes'),
      h('span', { class: 'muted small' }, 'Generates the file changes and validates them.')));
}

async function stage(box) {
  clear(box); put(box, h('p', { class: 'muted' }, 'Staging and validating (this round-trips the area through nwn_gff)…'));
  try {
    const r = await api('/api/camps/stage', { method: 'POST', body: { plan: cleanPlan() } });
    clear(box);
    const c = issueCounts(r.issues);
    put(box, h('div', { class: 'card' },
      h('div', { class: 'row' }, c.error ? h('span', { class: 'badge error' }, `${c.error} errors`) : h('span', { class: 'badge good' }, 'valid'),
        h('span', { class: 'badge warning' }, `${c.warning} warnings`), h('a', { class: 'right', href: `/changes#${r.id}` }, 'Review & apply →')),
      h('ul', { class: 'small', style: { paddingLeft: '16px' } }, r.files.map(f => h('li', {}, `${f.action === 'create' ? 'new' : 'edit'} ${f.rel} (+${f.added} −${f.removed})`)), r.notes.map(n => h('li', { class: 'muted' }, n))),
      issueList(r.issues)));
    S.dirty = false;
    if (!r.ok) toast('Staged, but validation found errors — fix them before applying', 'error');
    else toast('Staged. Review it on the Changes page.', 'good');
  } catch (e) { clear(box); put(box, h('div', { class: 'issue error' }, e.message)); }
}

// ----------------------------------------------------------------- toolbar
function renderToolbar() {
  clear(toolbar);
  const tbtn = (label, title, fn, active = false) => h('button', { class: `small${active ? ' active' : ''}`, title, onclick: fn }, label);
  const layer = (key, label) => h('label', { style: { display: 'inline-flex', gap: '4px', alignItems: 'center', margin: 0, color: 'var(--text)' } },
    h('input', { type: 'checkbox', checked: map.layers[key], onchange: e => map.setLayers({ [key]: e.target.checked }) }), label);
  put(toolbar, 
    tbtn('Select (Esc)', 'select / move objects', () => setTool({ type: 'select' }), S.tool.type === 'select'),
    tbtn('Fit', 'fit area to view (F)', () => map.fit()),
    tbtn('Undo', 'Ctrl+Z', undo),
    h('span', { class: 'muted small', style: { margin: '0 6px' } }, '|'),
    layer('tiles', 'tiles'), map.walk ? layer('walk', 'walkable') : null, layer('grid', 'grid'), layer('existing', 'existing objects'), layer('camp', 'camp spots'),
    map.walk ? null : layer('hints', 'walkable hints'), layer('labels', 'labels'),
    h('label', { style: { display: 'inline-flex', gap: '4px', alignItems: 'center', margin: 0, color: 'var(--text)' } },
      h('input', { type: 'checkbox', checked: map.snap > 0, onchange: e => { map.snap = e.target.checked ? 0.5 : 0; } }), 'snap 0.5 m'),
    h('span', { class: 'muted small', style: { margin: '0 6px' } }, '|'),
    h('label', { style: { margin: 0, color: 'var(--text)' } }, 'rotation'),
    h('input', { type: 'number', step: 15, value: S.rotation, style: { width: '70px' }, oninput: e => { S.rotation = Number(e.target.value) || 0; } }),
    tbtn('⟲', 'rotate placement −15° (Shift+R)', () => { S.rotation = (S.rotation + 345) % 360; renderToolbar(); }),
    tbtn('⟳', 'rotate placement +15° (R)', () => { S.rotation = (S.rotation + 15) % 360; renderToolbar(); }),
    h('span', { class: 'muted small right' }, 'wheel = zoom · right-drag / Space-drag = pan · Alt = no snap'));
}

function redrawAll() {
  map.hidePlan = S.plan.id;
  map.setPlan(S.plan.objects);
  map.setSelected(S.sel === null ? [] : [S.sel]);
  renderArea(); renderPlan(); renderTabs(); renderGroups(); renderEvents(); renderCamp(); renderSelection(); renderStage(); hudUpdate();
  syncCamp(); eventInfoSoon();
}

// ------------------------------------------------------------------ keyboard
window.addEventListener('keydown', e => {
  const tag = (document.activeElement || {}).tagName || '';
  if (/INPUT|TEXTAREA|SELECT/.test(tag)) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); return; }
  if (e.key === 'Escape') { setTool({ type: 'select' }); return; }
  if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); removeSelected(); return; }
  if (e.key.toLowerCase() === 'f') { map.fit(); return; }
  if (e.key.toLowerCase() === 'r') {
    const d = e.shiftKey ? -15 : 15;
    if (S.tool.type === 'select') rotateSelected(d); else { S.rotation = (S.rotation + d + 360) % 360; renderToolbar(); if (hoverPos) hover(hoverPos.x, hoverPos.y); }
    return;
  }
  const step = e.shiftKey ? 2 : 0.5;
  if (e.key === 'ArrowLeft') { e.preventDefault(); nudge(-step, 0); }
  if (e.key === 'ArrowRight') { e.preventDefault(); nudge(step, 0); }
  if (e.key === 'ArrowUp') { e.preventDefault(); nudge(0, step); }
  if (e.key === 'ArrowDown') { e.preventDefault(); nudge(0, -step); }
});
window.addEventListener('beforeunload', e => { if (S.plan.objects.length && S.dirty) { e.preventDefault(); e.returnValue = ''; } });

// -------------------------------------------------------------------- start
renderToolbar();
redrawAll();
const hashArea = /area=([A-Za-z0-9_]+)/.exec(location.hash);
const hashPlan = /plan=([a-z0-9_]+)/.exec(location.hash);
if (hashPlan) loadPlan(hashPlan[1]);
else if (hashArea) chooseArea(hashArea[1]);
