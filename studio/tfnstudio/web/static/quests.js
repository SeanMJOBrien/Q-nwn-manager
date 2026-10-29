import { $, h, api, session, clear, navbar, toast, modal, searchList, issueList, issueCounts, debounce, fmtNum, put } from '/static/common.js';
import { AreaMap } from '/static/areamap.js';

const app = $('#app');
await navbar('/quests');
app.className = 'full';

const info = await session().catch(() => ({ profile: 'tfn', features: { legacy_quest_scripts: true } }));
const GENERIC = info.profile === 'generic';
const [areas, creatures, items, saved, journal] = await Promise.all([
  api('/api/areas'), api('/api/palette/creatures'), api('/api/items'), api('/api/specs/quests'), api('/api/journal')]);
if (GENERIC && !creatures.some(c => c.resref === 'qs_npc'))   // installed with the first quest
  creatures.push({ resref: 'qs_npc', name: 'Quest NPC template (installed with your first quest)', cr: 1, kind: 'npc', conversation: '', plot: 1 });
const creatureBy = Object.fromEntries(creatures.map(c => [c.resref, c]));

const VIAS = { talk: 'Talk to an NPC', kill: 'Kill a creature', pickup: 'Pick up an item', explore: 'Enter an area' };
const RESREF = /^[a-z0-9_]{1,16}$/;

function blank() {
  return {
    tag: 'q_', name: '', priority: 2, script_style: 'modern',
    giver: { mode: 'new', resref: '', name: '', clone_from: GENERIC ? 'qs_npc' : 'jolie', greeting: '', place: null },
    stages: [
      { n: 1, via: 'talk', journal: '', offer: '', accept_reply: '', accept: '', decline_reply: '', decline: '', reminder: '' },
      { n: 2, via: 'talk', journal: '', text: '', reply: '', done: '', reward: {} },
    ],
  };
}

let spec = blank();
let dirty = false;

// ------------------------------------------------------------------- layout
put(document.body, h('datalist', { id: 'reward-items' }, items.map(i => h('option', { value: i.resref }, i.name))));
const left = h('div', { class: 'pane-left' });
const center = h('div', { class: 'pane-center', style: { padding: '16px', overflow: 'auto' } });
const right = h('div', { class: 'pane-right' });
put(app, left, center, right);

// ---------------------------------------------------------------- left pane
function renderLeft() {
  clear(left);
  put(left, h('h2', {}, 'Quests'),
    h('button', { class: 'primary', onclick: () => confirmDiscard(() => { spec = blank(); dirty = false; renderAll(); }) }, '+ New quest'),
    h('h4', { style: { marginTop: '14px' } }, `Your drafts (${saved.length})`),
    saved.length ? h('div', { class: 'list' }, saved.map(s => h('div', { class: 'item', onclick: () => confirmDiscard(() => loadSaved(s.id)) }, h('b', {}, s.title), h('span', { class: 'sub mono' }, s.id))))
      : h('p', { class: 'muted small' }, 'Save a quest to keep working on it later (stored in specs/quests/).'),
    h('h4', { style: { marginTop: '14px' } }, `Existing TFN quests (${journal.length})`));
  const list = searchList({
    items: () => journal, placeholder: 'Search the journal…',
    filter: (q, t) => !t || (q.tag + ' ' + q.name).toLowerCase().includes(t),
    render: q => h('div', {}, h('b', {}, q.name || q.tag), h('span', { class: 'sub' }, `${q.stages.length} stages`)),
    onPick: q => showExisting(q),
  });
  put(left, list.el, h('p', { class: 'muted small' }, 'Read-only: see how a real quest is wired (which NPC, creature or item advances each stage).'));
}

function showExisting(q) {
  const wiring = (q.wiring || []).slice().sort((a, b) => a.stage - b.stage);
  const body = h('div', {},
    h('p', { class: 'muted' }, `Tag ${q.tag} · priority ${q.priority}`),
    h('h4', {}, 'Journal'), h('table', {}, h('tbody', {}, q.stages.map(s => h('tr', {}, h('td', { style: { width: '40px' } }, String(s.id) + (s.end ? ' ✔' : '')), h('td', {}, s.text))))),
    h('h4', { style: { marginTop: '12px' } }, 'Wired by'),
    wiring.length ? h('table', {}, h('thead', {}, h('tr', {}, ['Stage', 'Type', 'What', 'Var'].map(t => h('th', {}, t)))),
      h('tbody', {}, wiring.map(w => h('tr', {}, h('td', {}, String(w.stage)), h('td', {}, w.type),
        h('td', { class: 'mono' }, w.type === 'placed' ? `${w.npc} in ${w.area}` : w.resref), h('td', { class: 'mono' }, w.var)))))
      : h('p', { class: 'muted' }, 'No creature/item/area carries this quest\'s variables (it may be advanced by a script).'));
  modal(q.name || q.tag, body);
}

async function loadSaved(id) {
  try {
    const got = await api(`/api/specs/quests/${id}`);
    // a draft saved before script styles existed was built with the older scripts: keep it that way
    spec = Object.assign(blank(), got, { script_style: got.script_style === 'modern' ? 'modern' : 'legacy' });
    dirty = false; renderAll();
  }
  catch (e) { toast(e.message, 'error'); }
}

async function confirmDiscard(fn) {
  if (!dirty) { fn(); return; }
  if (await modal('Discard unsaved changes?', h('p', {}, 'The quest you are editing has unsaved changes.'),
    [{ label: 'Cancel', value: false }, { label: 'Discard', value: true, danger: true }])) fn();
}

// ----------------------------------------------------------- form helpers
const changed = () => { dirty = true; describe(); };

// Top-right switch between the two ways a quest's dialog is wired (see the manual, "Script style").
const STYLE_INFO = {
  modern: 'Modern: one generic script per check, told the quest slot through a dialog parameter (target=3). Works for every slot; this is the recommended style for new quests.',
  legacy: 'Older: TFN\'s slot-numbered scripts (dlg_q_chk_atc3 ...). Choose this to match older quests exactly.',
};
const styleBtn = h('button', { class: 'small', id: 'script-style' });
if (info.features && info.features.legacy_quest_scripts !== false) document.querySelector('header.top .meta')?.prepend(styleBtn);
function renderStyleButton() {
  const modern = spec.script_style !== 'legacy';
  styleBtn.textContent = `Quest scripts: ${modern ? 'Modern' : 'Older'} ⇄`;
  styleBtn.title = STYLE_INFO[modern ? 'modern' : 'legacy'] + '\nClick to switch to ' + (modern ? 'the older style.' : 'the modern style.');
}
styleBtn.onclick = () => {
  spec.script_style = spec.script_style === 'legacy' ? 'modern' : 'legacy';
  renderStyleButton(); changed();
  toast(STYLE_INFO[spec.script_style], 'good');
};

function field(label, input, hint) {
  return h('div', { class: 'field' }, h('label', {}, label), input, hint ? h('div', { class: 'muted small' }, hint) : null);
}
function text(obj, key, { placeholder = '', maxlength, onInput } = {}) {
  return h('input', { type: 'text', value: obj[key] ?? '', placeholder, maxlength, style: { width: '100%' },
    oninput: e => { obj[key] = e.target.value; onInput && onInput(); changed(); } });
}
function area(obj, key, rows = 3, placeholder = '') {
  return h('textarea', { rows, placeholder, oninput: e => { obj[key] = e.target.value; changed(); } }, obj[key] ?? '');
}
function areaSelect(obj, key, allowNone = true) {
  return h('select', { onchange: e => { obj[key] = e.target.value; changed(); } },
    allowNone ? h('option', { value: '' }, '(none)') : null,
    areas.map(a => h('option', { value: a.resref, selected: obj[key] === a.resref }, `${a.name || a.resref} (${a.resref})`)));
}

async function pickCreature(title, kinds) {
  return new Promise(async resolve => {
    let chosen = null;
    const list = searchList({
      items: () => creatures.filter(c => !kinds || kinds.includes(c.kind)), placeholder: 'Search creatures…',
      filter: (c, q) => !q || (c.resref + ' ' + c.name).toLowerCase().includes(q),
      render: c => h('div', {}, h('b', {}, c.name || c.resref), h('span', { class: 'mono muted small' }, ` ${c.resref}`), h('span', { class: 'sub' }, `CR ${fmtNum(c.cr)} · ${c.kind}`)),
      onPick: c => { chosen = c; },
    });
    list.el.querySelector('.list').style.maxHeight = '420px';
    const r = await modal(title, list.el, [{ label: 'Cancel', value: false }, { label: 'Use selected', value: true, primary: true }]);
    resolve(r ? chosen : null);
  });
}

async function pickPosition(areaResref, current) {
  if (!areaResref) { toast('Choose an area first', 'warn'); return null; }
  const [detail, walk] = await Promise.all([api(`/api/areas/${areaResref}`), api(`/api/areas/${areaResref}/walk`).catch(() => null)]);
  const wrap = h('div', { class: 'mapwrap', style: { height: '460px', borderRadius: '8px', overflow: 'hidden' } });
  const canvas = h('canvas', { tabindex: 0 });
  const hud = h('div', { class: 'maphud' }, 'click to choose a spot · wheel zoom · right-drag pans');
  put(wrap, canvas, hud);
  let pos = current && current.x !== undefined ? { x: current.x, y: current.y } : null;
  const body = h('div', {}, wrap, h('p', { class: 'muted small' }, 'Tip: enable existing objects as a guide; spots near creatures and waypoints are known to be walkable.'));
  setTimeout(() => {
    const m = new AreaMap(canvas, {
      onClick: (x, y) => { pos = { x, y }; m.setPlan([{ kind: 'creature', x, y, facing: current && current.facing || 90 }]); hud.textContent = `x ${x.toFixed(1)}  y ${y.toFixed(1)}` + (m.walkAt(x, y) === 0 ? '  — NOT walkable' : ''); },
      onHover: (x, y) => { if (x !== null && !pos) hud.textContent = `x ${x.toFixed(1)}  y ${y.toFixed(1)}` + (m.walkAt(x, y) === 0 ? '  (not walkable)' : ''); },
    });
    m.layers.hints = !walk || !walk.available; m.setTool('place'); m.setArea(detail); m.setWalk(walk);
    if (pos) m.setPlan([{ kind: 'creature', x: pos.x, y: pos.y, facing: 90 }]);
  }, 30);
  const ok = await modal(`Pick a position in ${detail.name || areaResref}`, body, [{ label: 'Cancel', value: false }, { label: 'Use this spot', value: true, primary: true }]);
  return ok ? pos : null;
}

function placeEditor(owner, label) {
  const p = owner.place || {};
  const upd = () => { owner.place = p.area ? { area: p.area, x: Number(p.x ?? 0), y: Number(p.y ?? 0), facing: Number(p.facing ?? 90) } : null; changed(); };
  const num = key => h('input', { type: 'number', step: 0.5, value: p[key] ?? '', style: { width: '78px' }, oninput: e => { p[key] = e.target.value === '' ? undefined : Number(e.target.value); upd(); } });
  const areaSel = h('select', { onchange: e => { p.area = e.target.value; upd(); } }, h('option', { value: '' }, '(do not place)'),
    areas.map(a => h('option', { value: a.resref, selected: p.area === a.resref }, `${a.name || a.resref} (${a.resref})`)));
  return h('div', { class: 'field' }, h('label', {}, label), areaSel,
    h('div', { class: 'row', style: { marginTop: '4px' } }, 'x', num('x'), 'y', num('y'), 'facing', num('facing'),
      h('button', { class: 'small', onclick: async () => {
        const pos = await pickPosition(p.area, p);
        if (pos) { p.x = pos.x; p.y = pos.y; upd(); renderStages(); renderGiver(); }
      } }, 'Pick on map…')));
}

// ------------------------------------------------------------------- sections
const basicsBox = h('div', {});
const giverBox = h('div', {});
const stagesBox = h('div', {});
put(center, basicsBox, giverBox, stagesBox);

function renderBasics() {
  clear(basicsBox);
  const tagIn = h('input', { type: 'text', value: spec.tag, maxlength: 27, style: { width: '100%' },
    oninput: e => { spec.tag = e.target.value.trim(); tagChip(); changed(); } });
  const chip = h('span', { class: 'chip' }, '');
  const tagChip = () => {
    const ok = /^[qb]_[a-z0-9_]{1,25}$/.test(spec.tag) && spec.tag.length <= 27;
    const exists = journal.some(q => q.tag === spec.tag && !saved.some(s => s.id === spec.tag));
    chip.className = 'chip ' + (ok ? (exists ? 'warn' : 'good') : 'bad');
    chip.textContent = !ok ? 'invalid' : exists ? 'tag used by a TFN quest' : 'ok';
  };
  tagChip();
  put(basicsBox, h('h1', {}, spec.name || 'New quest'),
    h('div', { class: 'card' },
      h('div', { class: 'grid3' },
        field('Journal tag (q_… quest, b_… bounty)', h('div', { class: 'row' }, h('div', { class: 'grow' }, tagIn), chip), 'max 27 chars; bounties (b_) can be redone every 6 h'),
        field('Quest name', text(spec, 'name', { placeholder: 'e.g. Wolves at the Clearing', onInput: () => { $('h1', center).textContent = spec.name || 'New quest'; } })),
        field('Journal priority', h('select', { onchange: e => { spec.priority = Number(e.target.value); changed(); } },
          [0, 1, 2, 3, 4].map(n => h('option', { value: n, selected: spec.priority === n }, String(n))))))));
}

function renderGiver() {
  clear(giverBox);
  const g = spec.giver;
  const modeSel = h('select', { onchange: e => { g.mode = e.target.value; renderGiver(); changed(); } },
    h('option', { value: 'new', selected: g.mode === 'new' }, 'Create a new NPC (clone an existing one)'),
    h('option', { value: 'existing', selected: g.mode === 'existing' }, 'Use an existing NPC'));
  const resrefIn = h('input', { type: 'text', value: g.resref, maxlength: 16, placeholder: g.mode === 'new' ? 'new NPC resref' : 'existing NPC resref', style: { width: '100%' },
    oninput: e => { g.resref = e.target.value.trim(); changed(); } });
  const cloneBtn = (obj, key, kinds) => h('button', { class: 'small', onclick: async () => {
    const c = await pickCreature(key === 'clone_from' ? 'Pick a creature to clone' : 'Pick an NPC', kinds);
    if (c) { obj[key === 'clone_from' ? 'clone_from' : 'resref'] = c.resref; renderGiver(); renderStages(); changed(); }
  } }, 'Browse…');
  put(giverBox, h('div', { class: 'card', style: { marginTop: '12px' } }, h('h2', {}, 'Quest giver'),
    field('NPC', modeSel),
    g.mode === 'new' ? h('div', {},
      h('div', { class: 'grid2' },
        field('New NPC resref', resrefIn, 'a-z 0-9 _, max 16. Also the dialog resref.'),
        field('Display name', text(g, 'name', { placeholder: 'e.g. Hunter Marek' }))),
      field('Clone appearance & stats from', h('div', { class: 'row' }, h('div', { class: 'grow' }, text(g, 'clone_from', { placeholder: 'creature resref (use Browse…)' })), cloneBtn(g, 'clone_from', ['npc', 'other', 'henchman', 'monster'])),
        creatureBy[g.clone_from] ? `${creatureBy[g.clone_from].name} (CR ${fmtNum(creatureBy[g.clone_from].cr)}, ${creatureBy[g.clone_from].kind})` : 'must exist in src/utc'),
      field('Greeting (when no quest applies)', text(g, 'greeting', { placeholder: 'Hello, traveler.' })),
      placeEditor(g, 'Place the NPC in an area (optional)'))
    : h('div', {},
      field('Existing NPC', h('div', { class: 'row' }, h('div', { class: 'grow' }, resrefIn), cloneBtn(g, 'resref', ['npc', 'other', 'henchman'])),
        creatureBy[g.resref] ? `${creatureBy[g.resref].name} — conversation: ${creatureBy[g.resref].conversation || '(none, a new dialog will be created)'}` : 'quest variables are added to the blueprint and every placed instance; quest nodes are merged into the existing dialog'))));
}

function renderStages() {
  clear(stagesBox);
  put(stagesBox, h('h2', { style: { marginTop: '16px' } }, 'Stages'),
    h('p', { class: 'muted small' }, 'Each stage is a journal entry. The PC moves from stage N−1 to N by the mechanism you choose. Stage 1 is always the giver\'s offer; the last stage completes the quest.'));
  spec.stages.forEach((st, i) => put(stagesBox, stageCard(st, i)));
  put(stagesBox, h('div', { class: 'row' }, Object.entries(VIAS).map(([via, label]) =>
    h('button', { onclick: () => { addStage(via); } }, `+ ${label}`))));
}

function renumber() { spec.stages.forEach((s, i) => { s.n = i + 1; }); }
function addStage(via) {
  // keep the final (completing) stage last: insert before it when it is a talk stage
  const st = { via, journal: '' };
  if (via === 'talk') Object.assign(st, { text: '', reply: '', reminder: '' });
  if (via === 'kill') st.target = { mode: 'new', resref: '', name: '', clone_from: '', boss: true, place: null };
  if (via === 'pickup') st.item = { resref: '', name: '', description: '', dropped_by: '' };
  if (via === 'explore') st.area = '';
  const at = Math.max(1, spec.stages.length - 1);
  spec.stages.splice(at, 0, st);
  renumber(); renderStages(); changed();
}

function stageCard(st, i) {
  const last = i === spec.stages.length - 1;
  const mover = h('div', { class: 'row right' },
    h('button', { class: 'small', disabled: i <= 1, title: 'move up', onclick: () => { [spec.stages[i - 1], spec.stages[i]] = [spec.stages[i], spec.stages[i - 1]]; renumber(); renderStages(); changed(); } }, '↑'),
    h('button', { class: 'small', disabled: i === 0 || last, title: 'move down', onclick: () => { [spec.stages[i + 1], spec.stages[i]] = [spec.stages[i], spec.stages[i + 1]]; renumber(); renderStages(); changed(); } }, '↓'),
    h('button', { class: 'small danger', disabled: spec.stages.length <= 2 || i === 0, onclick: () => { spec.stages.splice(i, 1); renumber(); renderStages(); changed(); } }, 'Remove'));
  const viaSel = i === 0 ? h('span', { class: 'chip' }, VIAS.talk + ' (offer)') : h('select', {
    onchange: e => { const v = e.target.value; const keep = { journal: st.journal, reward: st.reward }; spec.stages[i] = Object.assign({ n: st.n, via: v }, keep, defaults(v)); renderStages(); changed(); } },
    Object.entries(VIAS).map(([v, l]) => h('option', { value: v, selected: st.via === v }, l)));
  const body = h('div', {}, field('Journal entry text (shown to the player)', area(st, 'journal', 3, 'What the player has learned / must do next.')));
  if (st.via === 'talk') put(body, talkFields(st, i));
  if (st.via === 'kill') put(body, killFields(st));
  if (st.via === 'pickup') put(body, pickupFields(st));
  if (st.via === 'explore') put(body, field('Area the player must enter', areaSelect(st, 'area', true)));
  put(body, rewardFields(st, last));
  return h('div', { class: 'stage-card' }, h('div', { class: 'head' }, h('span', { class: 'stage-num' }, String(st.n)), viaSel,
    last ? h('span', { class: 'chip good' }, 'completes the quest') : null, mover), body);
}

function defaults(via) {
  if (via === 'talk') return { text: '', reply: '', reminder: '' };
  if (via === 'kill') return { target: { mode: 'new', resref: '', name: '', clone_from: '', boss: true, place: null } };
  if (via === 'pickup') return { item: { resref: '', name: '', description: '', dropped_by: '' } };
  return { area: '' };
}

function talkFields(st, i) {
  const wrap = h('div', {});
  if (i === 0) {
    put(wrap, field('NPC offers the quest', area(st, 'offer', 3, 'I could use some help.  (what the giver says when the player first talks to them)')),
      h('div', { class: 'grid2' }, field('Player accepts', text(st, 'accept_reply', { placeholder: "I'll help you." })), field('NPC replies', text(st, 'accept', { placeholder: 'Thank you. Be careful out there.' }))),
      h('div', { class: 'grid2' }, field('Player declines', text(st, 'decline_reply', { placeholder: 'Not right now.' })), field('NPC replies', text(st, 'decline', { placeholder: 'Perhaps another time.' }))));
  } else {
    put(wrap, field('NPC says when the player returns (advances the quest)', area(st, 'text', 2, 'Well done.  (e.g. Well done! Here is your pay.)')),
      field('Player\'s reply (ends the conversation)', text(st, 'reply', { placeholder: 'optional' })));
    put(wrap, field('Different NPC? (existing resref, optional)', h('input', { type: 'text', value: (st.npc && st.npc.resref) || '', placeholder: 'leave empty for the giver', style: { width: '100%' },
      oninput: e => { const v = e.target.value.trim(); if (v) st.npc = { mode: 'existing', resref: v }; else delete st.npc; changed(); } })));
  }
  const nextIsTalk = spec.stages[i + 1] && spec.stages[i + 1].via === 'talk' && !(spec.stages[i + 1].npc);
  const last = i === spec.stages.length - 1;
  if (last) put(wrap, field('NPC says after completion', text(st, 'done', { placeholder: 'Thank you again for your help.' })));
  else if (!nextIsTalk) put(wrap, field('NPC reminder while the quest is in progress', text(st, 'reminder', { placeholder: 'Have you finished yet? I\'m counting on you.' })));
  return wrap;
}

function killFields(st) {
  const t = st.target;
  const cloneBtn = h('button', { class: 'small', onclick: async () => {
    const c = await pickCreature(t.mode === 'new' ? 'Pick a creature to clone' : 'Pick the target creature', ['monster', 'other', 'npc']);
    if (c) { t[t.mode === 'new' ? 'clone_from' : 'resref'] = c.resref; renderStages(); changed(); }
  } }, 'Browse…');
  return h('div', {},
    h('div', { class: 'grid2' }, field('Target', h('select', { onchange: e => { t.mode = e.target.value; renderStages(); changed(); } },
        h('option', { value: 'new', selected: t.mode === 'new' }, 'New named boss (clone of a creature)'),
        h('option', { value: 'existing', selected: t.mode === 'existing' }, 'Existing creature blueprint'))),
      field('Resref', text(t, 'resref', { placeholder: t.mode === 'new' ? 'new resref e.g. alpha_wolf' : 'existing resref', maxlength: 16 }))),
    t.mode === 'new' ? h('div', { class: 'grid2' }, field('Display name', text(t, 'name', { placeholder: 'e.g. Alpha Wolf' })),
      field('Clone from', h('div', { class: 'row' }, h('div', { class: 'grow' }, text(t, 'clone_from', { placeholder: 'creature resref' })), cloneBtn),
        creatureBy[t.clone_from] ? `${creatureBy[t.clone_from].name} CR ${fmtNum(creatureBy[t.clone_from].cr)}` : '')) : h('div', { class: 'row' }, cloneBtn,
      h('span', { class: 'issue warning' }, 'Every spawn of an existing blueprint advances the quest. Prefer a new named boss.')),
    h('label', { style: { display: 'flex', gap: '6px', alignItems: 'center', color: 'var(--text)' } }, h('input', { type: 'checkbox', checked: t.boss !== false, onchange: e => { t.boss = e.target.checked; changed(); } }), 'boss (better loot / XP / treasure-map chance)'),
    t.mode === 'new' ? placeEditor(t, 'Place the target in an area (optional)') : null);
}

function pickupFields(st) {
  const it = st.item;
  const killTargets = spec.stages.filter(s => s.via === 'kill' && s.target && s.target.resref).map(s => s.target.resref);
  const dl = h('datalist', { id: 'dropped-by' }, killTargets.map(r => h('option', { value: r })));
  return h('div', {}, h('div', { class: 'grid2' },
      field('Quest item resref', text(it, 'resref', { placeholder: 'e.g. q_alphapelt', maxlength: 16 })), field('Item name', text(it, 'name', { placeholder: 'e.g. Alpha Wolf Pelt' }))),
    field('Item description', area(it, 'description', 2)),
    field('Carried by (creature resref; a kill target above is ideal)', h('div', {}, h('input', { type: 'text', list: 'dropped-by', value: it.dropped_by || '', style: { width: '100%' },
      oninput: e => { it.dropped_by = e.target.value.trim(); changed(); } }), dl),
      'The item has Tag "quest": picking it up advances the stage and the item is consumed. Leave empty to place it yourself.'));
}

function rewardFields(st, last) {
  st.reward = st.reward || {};
  const rw = st.reward;
  const set = (k, v) => { if (v === '' || v === null || Number.isNaN(v) || v === 0) delete rw[k]; else rw[k] = v; changed(); };
  return h('details', { open: Object.keys(rw).length > 0, style: { marginTop: '6px' } },
    h('summary', { class: 'muted' }, `Rewards when this stage is reached${last ? ' (usually here)' : ''}`),
    h('div', { class: 'row', style: { marginTop: '6px' } },
      h('label', { style: { margin: 0 } }, 'XP tier'), h('select', { onchange: e => set('xp_tier', Number(e.target.value)) },
        [0, 1, 2, 3, 4].map(n => h('option', { value: n, selected: (rw.xp_tier || 0) === n }, n ? `${n} (${[50, 100, 200, 400][n - 1]} base)` : 'none'))),
      h('label', { style: { margin: 0 } }, 'for level'), h('input', { type: 'number', min: 1, max: 40, value: rw.xp_level ?? '', oninput: e => set('xp_level', Number(e.target.value)) }),
      h('label', { style: { margin: 0 } }, 'gold'), h('input', { type: 'number', min: 0, value: rw.gold ?? '', oninput: e => set('gold', Number(e.target.value)) }),
      h('label', { style: { margin: 0 } }, 'item'), h('input', { type: 'text', list: 'reward-items', value: rw.item || '', placeholder: 'resref', style: { width: '140px' }, oninput: e => set('item', e.target.value.trim()) })),
    rw.xp_tier && !rw.xp_level ? h('div', { class: 'issue warning' }, 'XP needs both a tier and a level') : null,
    h('p', { class: 'muted small' }, 'Handled by TFN\'s AdvanceQuest: XP scales with the player\'s level vs. the quest level (20–150%), gold is Charisma-modified.'));
}

// -------------------------------------------------------------- right pane
const planBox = h('div', {});
const actionBox = h('div', {});
const resultBox = h('div', {});
put(right, planBox, actionBox, resultBox);

const describe = debounce(async () => {
  clear(planBox);
  put(planBox, h('h2', {}, 'Mechanism plan'));
  try {
    const r = await api('/api/quests/describe', { method: 'POST', body: { spec: cleanSpec() } });
    put(planBox, h('table', {}, h('tbody', {}, r.stages.map(s => h('tr', {},
      h('td', { style: { width: '28px' } }, h('span', { class: 'stage-num' }, String(s.stage))),
      h('td', {}, h('b', {}, s.how), s.end ? h('span', { class: 'chip good', style: { marginLeft: '6px' } }, 'end') : null,
        h('div', { class: 'muted small' }, s.journal.slice(0, 90) + (s.journal.length > 90 ? '…' : '')),
        Object.keys(s.reward || {}).length ? h('div', { class: 'small' }, 'reward: ' + Object.entries(s.reward).map(([k, v]) => `${k}=${v}`).join(', ')) : null))))));
  } catch (e) { put(planBox, h('div', { class: 'issue warning' }, e.message)); }
}, 350);

function cleanSpec() {
  const s = JSON.parse(JSON.stringify(spec));
  for (const st of s.stages) {
    if (st.reward) {
      for (const k of Object.keys(st.reward)) if (st.reward[k] === '' || st.reward[k] === 0) delete st.reward[k];
      if (!Object.keys(st.reward).length) delete st.reward;
    }
    if (st.via === 'kill' && st.target && !st.target.place) delete st.target.place;
  }
  if (!s.giver.place) delete s.giver.place;
  return s;
}

function renderActions() {
  clear(actionBox);
  put(actionBox, h('div', { class: 'row', style: { marginTop: '12px' } },
    h('button', { class: 'primary', onclick: stage }, 'Stage changes'), h('button', { onclick: save }, 'Save draft'),
    h('span', { class: 'muted small' }, 'Staging generates journal, dialog, variables and validates them.')));
}

async function save() {
  if (!/^[qb]_[a-z0-9_]{1,25}$/.test(spec.tag)) { toast('Set a valid journal tag first', 'warn'); return; }
  try {
    const r = await api('/api/specs/quests', { method: 'POST', body: { spec: cleanSpec() } });
    dirty = false;
    if (!saved.some(s => s.id === r.id)) saved.push({ id: r.id, title: spec.name || r.id });
    renderLeft(); toast(`Saved specs/quests/${r.id}.json`, 'good');
  } catch (e) { toast(e.message, 'error'); }
}

async function stage() {
  clear(resultBox);
  put(resultBox, h('p', { class: 'muted' }, 'Staging and validating…'));
  try {
    const r = await api('/api/quests/stage', { method: 'POST', body: { spec: cleanSpec() } });
    clear(resultBox);
    const c = issueCounts(r.issues);
    put(resultBox, h('div', { class: 'card', style: { marginTop: '12px' } },
      h('div', { class: 'row' }, c.error ? h('span', { class: 'badge error' }, `${c.error} errors`) : h('span', { class: 'badge good' }, 'valid'),
        h('span', { class: 'badge warning' }, `${c.warning} warnings`), h('a', { class: 'right', href: `/changes#${r.id}` }, 'Review & apply →')),
      h('h4', { style: { marginTop: '10px' } }, 'Files'),
      h('ul', { class: 'small', style: { paddingLeft: '16px' } }, r.files.map(f => h('li', {}, `${f.action === 'create' ? 'new' : 'edit'} ${f.rel}`))),
      r.notes.length ? h('ul', { class: 'small muted', style: { paddingLeft: '16px' } }, r.notes.map(n => h('li', {}, n))) : null,
      issueList(r.issues),
      ...(r.report.dialogs || []).map(d => h('details', {}, h('summary', {}, `Dialog ${d.resref}`), h('pre', { class: 'outline' }, d.outline)))));
    dirty = false;
    toast(r.ok ? 'Staged. Review it on the Changes page.' : 'Staged, but validation found errors', r.ok ? 'good' : 'error');
  } catch (e) { clear(resultBox); put(resultBox, h('div', { class: 'issue error', style: { marginTop: '12px' } }, e.message)); }
}

function renderAll() { renderStyleButton(); renderLeft(); renderBasics(); renderGiver(); renderStages(); renderActions(); clear(resultBox); describe(); }

window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
renderAll();
const hashQuest = /quest=([a-z0-9_]+)/.exec(location.hash);
if (hashQuest) loadSaved(hashQuest[1]);
