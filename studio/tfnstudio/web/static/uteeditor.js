// Reusable encounter-blueprint (.ute) editor with live expected-mix preview.
import { h, api, clear, debounce, searchList, fmtNum, put } from '/static/common.js';

export const DIFFICULTIES = [
  [0, 'Very easy', 5], [1, 'Easy', 10], [2, 'Normal', 15], [3, 'Hard', 20], [4, 'Impossible', 25]];

export function blankSpec() {
  return { resref: '', name: '', difficulty: 2, creatures: [], rare: '' };
}

/**
 * opts: { creatures: [...palette], areas: [...compact areas], spec, onChange(spec), existing: Set(resrefs) }
 * Returns { el, getSpec, setSpec, refreshPreview }.
 */
export function createUteEditor(opts) {
  let spec = JSON.parse(JSON.stringify(opts.spec || blankSpec()));
  const byRes = Object.fromEntries(opts.creatures.map(c => [c.resref, c]));
  const root = h('div', {});
  const previewBox = h('div', {});
  let previewSpawns = 10;
  let previewArea = '';

  const emit = () => { opts.onChange && opts.onChange(spec); preview(); };

  const resrefInput = h('input', { type: 'text', maxlength: 16, placeholder: 'encounter resref (a-z 0-9 _)', style: { width: '100%' },
    oninput: e => { spec.resref = e.target.value.trim(); badge(); emit(); } });
  const nameInput = h('input', { type: 'text', placeholder: 'display name (optional)', style: { width: '100%' },
    oninput: e => { spec.name = e.target.value; opts.onChange && opts.onChange(spec); } });
  const diffSel = h('select', { onchange: e => { spec.difficulty = Number(e.target.value); emit(); } },
    DIFFICULTIES.map(([v, n, p]) => h('option', { value: v }, `${n} — ${p}% unique`)));
  const rareInput = h('input', { type: 'text', list: 'rare-creatures', placeholder: 'rare creature resref (optional)', style: { width: '100%' },
    oninput: e => { spec.rare = e.target.value.trim(); emit(); } });
  const datalist = h('datalist', { id: 'rare-creatures' }, opts.creatures.map(c => h('option', { value: c.resref }, `${c.name} (CR ${fmtNum(c.cr)})`)));
  const status = h('span', { class: 'chip' }, '');
  const creatureTable = h('div', {});

  function badge() {
    const ok = /^[a-z0-9_]{1,16}$/.test(spec.resref);
    const exists = opts.existing && opts.existing.has(spec.resref);
    status.className = 'chip ' + (!spec.resref ? '' : !ok ? 'bad' : exists ? 'warn' : 'good');
    status.textContent = !spec.resref ? '' : !ok ? 'invalid resref' : exists ? 'editing existing' : 'new';
  }

  function drawCreatures() {
    clear(creatureTable);
    if (!spec.creatures.length) { put(creatureTable, h('p', { class: 'muted small' }, 'No creatures yet — pick some below.')); return; }
    put(creatureTable, h('table', {},
      h('thead', {}, h('tr', {}, ['Creature', 'CR', 'Pool', ''].map(t => h('th', {}, t)))),
      h('tbody', {}, spec.creatures.map((c, i) => {
        const info = byRes[c.resref];
        return h('tr', {},
          h('td', {}, h('b', {}, info ? info.name : c.resref), ' ', h('span', { class: 'mono muted small' }, c.resref)),
          h('td', {}, info ? fmtNum(info.cr) : '?'),
          h('td', {}, h('select', { onchange: e => { c.unique = e.target.value === 'unique'; emit(); } },
            h('option', { value: 'common', selected: !c.unique }, 'common'), h('option', { value: 'unique', selected: !!c.unique }, 'unique (single spawn)'))),
          h('td', {}, h('button', { class: 'small danger', onclick: () => { spec.creatures.splice(i, 1); drawCreatures(); emit(); } }, '✕')));
      }))));
  }

  const picker = searchList({
    items: () => opts.creatures,
    placeholder: 'Search creatures by name or resref (e.g. wolf, bandit)…',
    filter: (c, q) => !q || (c.resref + ' ' + c.name + ' ' + c.kind).toLowerCase().includes(q),
    render: c => h('div', {}, h('b', {}, c.name || c.resref), h('span', { class: 'mono muted small' }, ` ${c.resref}`),
      h('span', { class: 'sub' }, `CR ${fmtNum(c.cr)} · ${c.kind}`)),
    onPick: c => {
      if (spec.creatures.some(x => x.resref === c.resref)) return;
      spec.creatures.push({ resref: c.resref, unique: false });
      drawCreatures(); emit();
    },
  });

  const spawnsInput = h('input', { type: 'number', min: 1, max: 200, value: previewSpawns, oninput: e => { previewSpawns = Math.max(1, Number(e.target.value) || 10); preview(); } });
  const areaSel = h('select', { onchange: e => { previewArea = e.target.value; preview(); } },
    h('option', { value: '' }, '(no area)'), (opts.areas || []).filter(a => a.cr).map(a => h('option', { value: a.resref }, `${a.name || a.resref} — cr ${a.cr}`)));

  const doPreview = debounce(async () => {
    clear(previewBox);
    if (!/^[a-z0-9_]{1,16}$/.test(spec.resref) || !spec.creatures.length) {
      put(previewBox, h('p', { class: 'muted small' }, 'Enter a resref and add at least one creature to preview.')); return;
    }
    try {
      const r = await api('/api/utes/preview', { method: 'POST', body: { spec, spawns: previewSpawns, area: previewArea } });
      const d = r.describe, m = r.mix;
      put(previewBox, 
        h('div', { class: 'row' }, h('span', { class: 'chip' }, `${d.difficulty_name}: ${d.unique_chance}% unique`),
          h('span', { class: 'chip' }, `${d.commons.length} common · ${d.uniques.length} unique`),
          m.rare_chance ? h('span', { class: 'chip warn' }, `${m.rare_chance}% rare: ${d.rare}`) : null),
        h('table', { style: { marginTop: '6px' } }, h('thead', {}, h('tr', {}, ['Creature', 'Expected / refresh'].map(t => h('th', {}, t)))),
          h('tbody', {}, m.rows.map(row => h('tr', {}, h('td', {}, byRes[row.resref] ? byRes[row.resref].name : row.resref), h('td', {}, fmtNum(row.expected, 2)))))),
        h('p', { class: 'muted small' }, `Spawns ${m.spawns_min}–${m.spawns_max} creatures per refresh (≈${m.expected_total}); average common CR ${m.avg_common_cr}.`),
        ...r.warnings.map(w => h('div', { class: 'issue warning' }, w)), ...r.cr_notes.map(w => h('div', { class: 'issue info' }, w)));
    } catch (e) { put(previewBox, h('div', { class: 'issue error' }, e.message)); }
  }, 300);
  function preview() { doPreview(); }

  function setSpec(s) {
    spec = JSON.parse(JSON.stringify(s));
    resrefInput.value = spec.resref || ''; nameInput.value = spec.name || ''; rareInput.value = spec.rare || '';
    diffSel.value = String(spec.difficulty ?? 2);
    badge(); drawCreatures(); preview();
  }

  put(root, 
    h('div', { class: 'grid2' },
      h('div', { class: 'field' }, h('label', {}, 'Resref'), h('div', { class: 'row' }, h('div', { class: 'grow' }, resrefInput), status)),
      h('div', { class: 'field' }, h('label', {}, 'Name'), nameInput)),
    h('div', { class: 'grid2' },
      h('div', { class: 'field' }, h('label', {}, 'Difficulty (unique chance)'), diffSel),
      h('div', { class: 'field' }, h('label', {}, 'Rare creature (15% per refresh)'), rareInput, datalist)),
    h('h4', {}, 'Creatures'), creatureTable,
    h('div', { class: 'field', style: { marginTop: '8px' } }, h('label', {}, 'Add creature'), picker.el),
    h('h4', {}, 'Preview'),
    h('div', { class: 'row', style: { marginBottom: '6px' } }, h('label', { style: { margin: 0 } }, 'Group spawns'), spawnsInput,
      h('label', { style: { margin: '0 0 0 10px' } }, 'Check CR against'), areaSel),
    previewBox);
  setSpec(spec);
  return { el: root, getSpec: () => JSON.parse(JSON.stringify(spec)), setSpec, refreshPreview: preview };
}
