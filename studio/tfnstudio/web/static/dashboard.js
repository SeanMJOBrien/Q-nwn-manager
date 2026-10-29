import { $, h, api, clear, navbar, toast, fmtTime, put } from '/static/common.js';

const app = $('#app');
let timer = null;

function toolChip(name, path) {
  return h('div', { class: 'row' }, h('b', { style: { width: '70px' } }, name),
    path ? h('span', { class: 'chip good' }, 'found') : h('span', { class: 'chip bad' }, 'missing'),
    h('span', { class: 'mono muted small' }, path || 'validation of this kind will be skipped'));
}

function render(s) {
  clear(app);
  const idx = s.index;
  const idxLine = idx.building
    ? h('span', { class: 'chip warn' }, `building… ${idx.progress}`)
    : idx.error ? h('span', { class: 'chip bad' }, idx.error)
    : h('span', { class: 'chip good' }, idx.seconds ? `ready (${idx.seconds}s)` : 'ready');

  put(app, 
    h('h1', {}, 'Extend The Frozen North'),
    h('p', { class: 'muted' }, 'Design quests, camps and spawn groups on a map, review the exact file changes, then apply them to the TFN source tree.'),
    h('div', { class: 'cards' },
      h('a', { class: 'card', href: '/camps', style: { color: 'inherit' } }, h('h2', {}, 'Camp Builder →'),
        h('p', { class: 'muted' }, 'Stamp camp prefabs or place props, creatures, spawn markers and event waypoints on an area map. Assigns random spawn groups and the area CR.')),
      h('a', { class: 'card', href: '/spawns', style: { color: 'inherit' } }, h('h2', {}, 'Spawn Designer →'),
        h('p', { class: 'muted' }, 'Author encounter blueprints (.ute): common and unique creatures, difficulty, rare spawn. See expected mixes and where each is used.')),
      h('a', { class: 'card', href: '/quests', style: { color: 'inherit' } }, h('h2', {}, 'Quest Builder →'),
        h('p', { class: 'muted' }, 'Build multi-stage quests with TFN\'s variable system: journal, giver dialog, kill targets, pickups, explore stages and rewards.')),
      h('a', { class: 'card', href: '/manual', target: '_blank', rel: 'noopener', style: { color: 'inherit' } }, h('h2', {}, 'Manual ↗'),
        h('p', { class: 'muted' }, 'Installation, startup, every page step by step, the command line and troubleshooting. Also readable without the studio: open MANUAL.html in the project folder.'))),
    h('div', { class: 'split', style: { marginTop: '16px' } },
      h('div', {},
        h('div', { class: 'card' }, h('h2', {}, 'TFN checkout'),
          h('table', {}, h('tbody', {},
            h('tr', {}, h('th', {}, 'Path'), h('td', { class: 'mono' }, s.tfn_root)),
            h('tr', {}, h('th', {}, 'Branch'), h('td', {}, `${s.branch || '?'} @ ${s.head || '?'}`)),
            h('tr', {}, h('th', {}, 'Uncommitted'), h('td', {}, `${s.dirty_files} file(s) `,
              h('span', { class: 'muted small' }, '— Apply refuses to overwrite files with uncommitted changes')))))),
        h('div', { class: 'card' }, h('h2', {}, 'Tools'),
          toolChip('nwn_gff', s.tools.nwn_gff), toolChip('nwnsc', s.tools.nwnsc), toolChip('nasher', s.tools.nasher),
          h('div', { class: 'row' }, h('b', { style: { width: '70px' } }, 'walkmesh'), s.walkmesh ? h('span', { class: 'chip good' }, 'game data found') : h('span', { class: 'chip warn' }, 'unavailable'),
            h('span', { class: 'muted small' }, s.walkmesh ? 'exact ground heights + walkability from the NWN install' : 'set $NWN_ROOT to your NWN install to get exact heights/walkability'))),
        h('div', { class: 'card' }, h('h2', {}, 'Content'),
          h('div', { class: 'row' }, Object.entries(s.counts).map(([k, v]) => h('span', { class: 'chip' }, `${v} .${k}`))),
          h('div', { class: 'row', style: { marginTop: '10px' } }, h('b', {}, 'Index'), idxLine,
            h('button', { class: 'small right', disabled: idx.building, onclick: async () => {
              try { await api('/api/index/refresh', { method: 'POST', body: {} }); toast('Index refresh started'); poll(); }
              catch (e) { toast(e.message, 'error'); } } }, 'Refresh index')))),
      h('div', {},
        h('div', { class: 'card' }, h('h2', {}, 'Change sets'),
          s.changes.length ? h('table', {}, h('thead', {}, h('tr', {}, ['Title', 'Kind', 'Files', 'State'].map(t => h('th', {}, t)))),
            h('tbody', {}, s.changes.slice(0, 12).map(c => h('tr', { class: 'clickable', onclick: () => { location.href = `/changes#${c.id}`; } },
              h('td', {}, c.title), h('td', {}, h('span', { class: 'chip' }, c.kind)), h('td', {}, String(c.files)),
              h('td', {}, c.applied ? h('span', { class: 'chip good' }, 'applied') : h('span', { class: 'chip warn' }, 'staged'))))))
            : h('p', { class: 'muted' }, 'Nothing staged yet. Build something, press Stage, and it shows up here.')),
        h('div', { class: 'card' }, h('h2', {}, 'After you apply'),
          h('ol', { style: { margin: 0, paddingLeft: '18px' } },
            h('li', {}, 'Build the module: ', h('code', {}, 'swamp model method run thefrozennorth-build build'), ' (run from ~/git).'),
            h('li', {}, 'Restart the server: ', h('code', {}, 'area_init'), ' reads spawn markers, area variables and quest NPCs at module load.'),
            h('li', {}, 'No reseed needed for camps, spawn groups and quests (new areas/tiles/transitions do).'),
            h('li', {}, 'Check object heights in the toolset — Z is inferred from neighbours.'))))));
}

async function poll() {
  clearTimeout(timer);
  try {
    const s = await api('/api/status');
    render(s);
    if (s.index.building) timer = setTimeout(poll, 1500);
  } catch (e) { clear(app); put(app, h('div', { class: 'card' }, h('b', {}, 'Cannot reach the studio server: '), e.message)); }
}

await navbar('/');
poll();
