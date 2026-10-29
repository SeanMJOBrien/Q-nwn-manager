import { $, h, api, clear, navbar, toast, searchList, issueList, issueCounts, fmtNum, put } from '/static/common.js';
import { createUteEditor, blankSpec } from '/static/uteeditor.js';

const app = $('#app');
await navbar('/spawns');
app.className = 'full';

const [utes, creatures, areas, saved] = await Promise.all([
  api('/api/utes'), api('/api/palette/creatures'), api('/api/areas'), api('/api/specs/utes')]);
const existing = new Set(utes.map(u => u.resref));

const left = h('div', { class: 'pane-left' });
const center = h('div', { class: 'pane-center', style: { padding: '16px', overflow: 'auto' } });
const right = h('div', { class: 'pane-right' });
put(app, left, center, right);

let editor = null;
let currentSaved = null;

const list = searchList({
  items: () => utes,
  placeholder: `Search ${utes.length} encounter blueprints…`,
  filter: (u, q) => !q || (u.resref + ' ' + u.name).toLowerCase().includes(q),
  render: u => h('div', {}, h('b', {}, u.resref), h('span', { class: 'sub' }, `${u.creatures.length} cr · ${u.used_by} area${u.used_by === 1 ? '' : 's'}`)),
  onPick: u => loadExisting(u.resref),
});

put(left, h('h2', {}, 'Encounter blueprints'),
  h('p', { class: 'muted small' }, 'A .ute is the data container TFN reads for random spawn groups (random1…random9 on an area).'),
  h('button', { class: 'primary', onclick: () => startNew() }, '+ New encounter'), h('div', { style: { height: '10px' } }), list.el,
  saved.length ? h('div', {}, h('h4', { style: { marginTop: '14px' } }, 'Saved drafts'),
    h('div', { class: 'list' }, saved.map(s => h('div', { class: 'item', onclick: () => loadDraft(s.id) }, s.title, h('span', { class: 'sub' }, 'draft'))))) : null);

function mount(spec) {
  clear(center); clear(right);
  editor = createUteEditor({ creatures, areas, spec, existing, onChange: () => {} });
  const result = h('div', {});
  put(center, h('h1', {}, spec.resref ? `Encounter: ${spec.resref}` : 'New encounter'), editor.el,
    h('div', { class: 'row', style: { marginTop: '14px' } },
      h('button', { class: 'primary', onclick: () => stage(result) }, 'Stage changes'),
      h('button', { onclick: saveDraft }, 'Save draft'),
      h('span', { class: 'muted small' }, 'Staging validates the result; nothing touches TFN until you apply it on the Changes page.')),
    result);
}

function startNew() { currentSaved = null; mount(blankSpec()); }

async function loadExisting(resref) {
  try {
    const r = await api(`/api/utes/${resref}`);
    mount(r.spec);
    put(right, h('h2', {}, 'Used by'), usageTable(r.usage),
      h('p', { class: 'muted small' }, 'Editing an existing blueprint rewrites its creature list, difficulty and rare; other fields are kept.'));
  } catch (e) { toast(e.message, 'error'); }
}

async function loadDraft(id) {
  try { mount(await api(`/api/specs/utes/${id}`)); } catch (e) { toast(e.message, 'error'); }
}

function usageTable(usage) {
  if (!usage.length) return h('p', { class: 'muted' }, 'Not used by any area yet.');
  return h('table', {}, h('thead', {}, h('tr', {}, ['Area', 'Grp', 'Spawns', 'CR'].map(t => h('th', {}, t)))),
    h('tbody', {}, usage.map(u => h('tr', {}, h('td', {}, h('a', { href: `/camps#area=${u.area}` }, u.name || u.area)),
      h('td', {}, `r${u.group}`), h('td', {}, String(u.spawns)), h('td', {}, u.cr ?? '')))));
}

async function saveDraft() {
  const spec = editor.getSpec();
  try { const r = await api('/api/specs/utes', { method: 'POST', body: { spec } }); toast(`Saved draft ${r.id}`, 'good'); }
  catch (e) { toast(e.message, 'error'); }
}

async function stage(box) {
  clear(box); put(box, h('p', { class: 'muted' }, 'Staging…'));
  try {
    const r = await api('/api/utes/stage', { method: 'POST', body: { spec: editor.getSpec() } });
    clear(box);
    const c = issueCounts(r.issues);
    put(box, h('div', { class: 'card', style: { marginTop: '12px' } },
      h('div', { class: 'row' }, h('b', {}, `Staged ${r.id}`), c.error ? h('span', { class: 'badge error' }, `${c.error} errors`) : h('span', { class: 'badge good' }, 'valid'),
        h('a', { class: 'right', href: `/changes#${r.id}` }, 'Review & apply →')),
      issueList(r.issues)));
  } catch (e) { clear(box); put(box, h('div', { class: 'issue error' }, e.message)); }
}

startNew();
