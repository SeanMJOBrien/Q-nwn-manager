// Quests page of the nwn-manager console. Collects a quest spec, shows the builder's plan, builds it into the project.
// The spec's fields come from the builder's own JSON Schema (GET quests/data), so a new builder option shows up under
// "More options" without a change here; this file only decides what is shown first and under which label.
(function () {
  'use strict';
  var root = document.getElementById('quests-app');
  var base = root.getAttribute('data-base');

  // ---------------------------------------------------------------- tiny DOM helpers
  function h(tag, attrs) {
    var el = document.createElement(tag);
    for (var k in attrs || {}) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else if (k === 'value' || k === 'checked' || k === 'selected' || k === 'disabled' || k === 'open') el[k] = v;
      else el.setAttribute(k, v);
    }
    for (var i = 2; i < arguments.length; i++) put(el, arguments[i]);
    return el;
  }
  function put(el) {
    for (var i = 1; i < arguments.length; i++) {
      var c = arguments[i];
      if (c === null || c === undefined || c === false) continue;
      if (Array.isArray(c)) c.forEach(function (x) { put(el, x); });
      else el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
    }
    return el;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

  // ---------------------------------------------------------------- talking to the console
  function token(name) {
    var el = document.querySelector('#quests-token input[name="' + name + '"]');
    return el ? el.value : '';
  }
  function get(path) {
    return fetch(base + path, { credentials: 'same-origin' }).then(answer);
  }
  function post(path, fields) {
    var body = new URLSearchParams();
    body.set('_csrf', token('_csrf'));
    for (var k in fields) body.set(k, fields[k]);
    return fetch(base + path, { method: 'POST', credentials: 'same-origin', body: body }).then(answer);
  }
  function answer(res) {
    return res.text().then(function (text) {
      var doc;
      try { doc = JSON.parse(text); } catch (e) {
        throw new Error(res.status === 403 ? 'The console was restarted or this page is old. Reload the page and try again.'
          : 'The console answered with something unexpected (HTTP ' + res.status + ').');
      }
      if (!doc.ok) {
        var err = new Error(doc.error || 'request failed');
        err.stage = doc.stage; err.field = doc.field;
        throw err;
      }
      return doc;
    });
  }

  // ---------------------------------------------------------------- what the form shows
  var KIND_HELP = {
    talk: 'talk to an NPC',
    return: 'go back to the quest giver',
    kill: 'kill a creature',
    pickup: 'pick up an item',
    explore: 'enter an area',
    trigger: 'walk into a spot',
    use: 'use a placeable',
    search: 'search a placeable (skill check)',
    deliver: 'hand an item to an NPC',
    rescue: 'free a captive',
    escort: 'escort an NPC to a place',
    custom: 'your own script advances it'
  };
  // Fields shown on a stage card for each kind, in order; the rest of the schema sits under "More options".
  var BY_KIND = {
    talk: ['to', 'text', 'reply', 'check'],
    return: ['text', 'reply'],
    kill: ['target', 'area'],
    pickup: ['itemName', 'item', 'from_creature', 'in', 'count'],
    explore: ['area'],
    trigger: ['area', 'x', 'y', 'radius'],
    use: ['target'],
    search: ['target', 'check', 'itemName', 'optional'],
    deliver: ['to', 'item', 'count', 'keep', 'missing'],
    rescue: ['target', 'plea'],
    escort: ['target', 'area', 'x', 'y', 'radius', 'plea', 'arrive'],
    custom: []
  };
  var FIRST_STAGE = ['offer', 'accept', 'decline'];        // extra lines on stage 1 (accepting the quest)
  var REQUIRED = {
    kill: ['target'], explore: ['area'], trigger: ['area', 'x', 'y'], use: ['target'], search: ['target', 'check'],
    rescue: ['target'], escort: ['target', 'area']
  };
  var LABELS = {
    name: 'Quest name (journal title)', giver: 'Quest giver', level: 'Party level (sizes the reward)',
    'do': 'The player must', journal: 'Journal entry', to: 'NPC', text: 'What the NPC says', reply: 'The player\'s answer',
    offer: 'The NPC\'s offer', accept: 'Player line that accepts', decline: 'Player line that declines',
    area: 'Area', x: 'X (metres)', y: 'Y (metres)', radius: 'Radius (metres)', item: 'Existing item',
    itemName: 'New quest item (name)', from_creature: 'Carried by creature', 'in': 'Inside container', count: 'How many',
    check: 'Skill check', reward: 'Reward', keep: 'The party keeps the item', missing: 'NPC line when the item is missing',
    plea: 'The NPC\'s plea', arrive: 'Line on arrival', optional: 'Optional clue (no journal entry)', spawn: 'Creatures that appear',
    reminder: 'NPC line while this is still to do'
  };
  var TARGET_LABEL = { kill: 'Creature to kill', use: 'Placeable to use', search: 'Placeable to search', rescue: 'Captive', escort: 'NPC to escort' };
  var HINTS = {
    'kill.area': 'Only when the creature is not placed yet: the builder places it in this area.',
    'pickup.item': 'Or pick an item that already exists, instead of a new one.',
    'pickup.from_creature': 'It drops when this creature dies.',
    'deliver.item': 'Leave empty to hand over the item an earlier stage gave or had picked up.',
    'escort.area': 'Where the NPC must arrive.'
  };
  var TOP_SHOWN = ['name', 'giver', 'level'];
  var TEMPLATE_FIELDS = ['template', 'target', 'item', 'itemName', 'to', 'area', 'captive', 'npc', 'dest', 'clues', 'check', 'journal', 'thanks', 'stages'];
  var PICKER = {
    giver: 'creature', to: 'creature', from_creature: 'creature', companion: 'creature', dismiss: 'creature', resref: 'creature',
    item: 'item', area: 'area', 'in': 'placeable', at: 'waypoint'
  };
  function pickFor(name, stageDo) {
    if (name === 'target') return stageDo === 'use' || stageDo === 'search' ? 'placeable' : 'creature';
    return PICKER[name] || null;
  }
  // Starting points: each fills the stage list; every field stays editable afterwards.
  var PRESETS = [
    { id: 'kill', title: 'Kill', blurb: 'kill a creature, report back',
      stages: [{ 'do': 'talk', journal: '' }, { 'do': 'kill', target: '', journal: '' }, { 'do': 'return', journal: '' }] },
    { id: 'fetch', title: 'Fetch', blurb: 'find an item, bring it to the giver',
      stages: [{ 'do': 'talk', journal: '' }, { 'do': 'pickup', itemName: '', journal: '' }, { 'do': 'deliver', journal: '' }] },
    { id: 'deliver', title: 'Deliver', blurb: 'carry a parcel to another NPC',
      stages: [{ 'do': 'talk', journal: '', reward: { item: '' } }, { 'do': 'deliver', to: '', journal: '' }] },
    { id: 'rescue', title: 'Rescue', blurb: 'free a captive, report back',
      stages: [{ 'do': 'talk', journal: '' }, { 'do': 'rescue', target: '', journal: '' }, { 'do': 'return', journal: '' }] },
    { id: 'escort', title: 'Escort', blurb: 'walk an NPC to a place',
      stages: [{ 'do': 'talk', journal: '' }, { 'do': 'escort', target: '', area: '', journal: '' }] },
    { id: 'investigate', title: 'Investigate', blurb: 'examine clues, report back',
      stages: [{ 'do': 'talk', journal: '' }, { 'do': 'use', target: '', journal: '' }, { 'do': 'use', target: '', journal: '' }, { 'do': 'return', journal: '' }] },
    { id: 'persuade', title: 'Persuade or fight', blurb: 'talk someone round, or kill them',
      stages: [{ 'do': 'talk', journal: '' }, { 'do': 'talk', to: '', check: { skill: 'persuade', dc: 15, 'else': 'fight' }, journal: '' },
        { 'do': 'kill', target: '', n: 2, journal: '' }, { 'do': 'return', journal: '' }] },
    { id: 'talk', title: 'Errand', blurb: 'talk to someone, report back',
      stages: [{ 'do': 'talk', journal: '' }, { 'do': 'talk', to: '', journal: '' }, { 'do': 'return', journal: '' }] }
  ];
  var PRESET_NOTE = {
    deliver: 'On stage 1, pick the parcel under "Item the giver hands over"; then say who gets it on stage 2.',
    fetch: 'On stage 2 say who carries the item or which container holds it.',
    persuade: 'Stages 2 and 3 are two ways to the same point: both carry number 2 (see "n" under More options on the kill stage).'
  };

  // ---------------------------------------------------------------- state
  var info = { ready: false, problems: [], notes: [] };
  var defs = {};
  var quests = [];
  var spec = null;              // set below, once copy() and the presets exist
  var snapshot = null;          // the spec as last saved, loaded or built
  var plan = null;              // {ok, dry, result | error}
  var busy = '';
  var presetNote = '';

  function blank() { return { name: '', giver: '', level: 3, stages: copy(PRESETS[0].stages) }; }
  function copy(v) { return JSON.parse(JSON.stringify(v)); }
  spec = blank();
  function clean(v) {            // drop empty values so the spec stays minimal
    if (Array.isArray(v)) return v.map(clean);
    if (v && typeof v === 'object') {
      var o = {};
      Object.keys(v).forEach(function (k) {
        var c = clean(v[k]);
        var emptyObj = c && typeof c === 'object' && !Array.isArray(c) && !Object.keys(c).length;
        if (c !== undefined && c !== '' && c !== null && !emptyObj) o[k] = c;
      });
      return o;
    }
    return v;
  }
  function dirty() {
    var now = JSON.stringify(clean(spec));
    if (snapshot === null) return now !== JSON.stringify(clean(blank()));
    return now !== snapshot;
  }
  function deref(s) { return (s && s.$ref ? defs[s.$ref.split('/').pop()] : s) || {}; }
  function changed() { plan = null; renderSide(); }

  // ---------------------------------------------------------------- field widgets
  var lists = h('div', { style: 'display:none' });
  function widget(def, value, set, name, ctx) {
    var d = deref(def);
    var label = (name === 'target' && ctx.stageDo && TARGET_LABEL[ctx.stageDo]) || LABELS[name] || name;
    var required = ctx.stageDo && !ctx.group && (name === 'journal' || (REQUIRED[ctx.stageDo] || []).indexOf(name) >= 0) ||
      ctx.top && (name === 'name' || name === 'giver');
    var hint = HINTS[(ctx.stageDo || '') + '.' + name] || (LABELS[name] ? '' : d.description || '');
    var note = hint ? h('div', { class: 'note q-hint' }, hint) : null;
    var where = ctx.group ? {} : { 'data-q-field': name, 'data-q-stage': ctx.stageIdx };
    var input;
    if (d['enum']) {
      input = h('select', { onchange: function (e) { set(e.target.value || undefined); } }, h('option', { value: '' }, '-'),
        d['enum'].map(function (o) { return h('option', { value: o, selected: o === value }, o); }));
    } else if (d.type === 'boolean') {
      input = h('input', { type: 'checkbox', checked: value === true, onchange: function (e) { set(e.target.checked ? true : undefined); } });
    } else if (d.type === 'number') {
      input = h('input', { type: 'number', value: value === undefined ? '' : value,
        oninput: function (e) { set(e.target.value === '' ? undefined : Number(e.target.value)); } });
    } else if (d.type === 'string') {
      var long = /journal|text|offer|reply|plea|prompt|arrive|missing|reminder|none|accept|decline|thanks|pass|fail/i.test(name);
      var pick = long ? null : pickFor(name, ctx.stageDo);
      input = h(long ? 'textarea' : 'input', { type: long ? null : 'text', rows: long ? 2 : null, value: value === undefined ? '' : value,
        list: pick ? 'q-list-' + pick : null,
        placeholder: pick ? 'pick a ' + pick + ' from the module, or type' : long && name !== 'journal' ? 'optional: a standard line is used when empty' : null,
        'class': required && !value ? 'q-missing' : null,
        oninput: function (e) { e.target.classList.toggle('q-missing', !!required && !e.target.value); set(e.target.value || undefined); } });
    } else if (d.type === 'object' && d.properties) {
      var sub = h('div', { class: 'q-group' });
      Object.keys(d.properties).forEach(function (k) {
        put(sub, widget(d.properties[k], (value || {})[k], function (x) {
          var n = copy(value || {});
          if (x === undefined) delete n[k]; else n[k] = x;
          value = Object.keys(n).length ? n : undefined;
          set(value);
        }, k, { stageDo: ctx.stageDo, group: name }));
      });
      return h('details', Object.assign({ class: 'q-field', open: value !== undefined }, where), h('summary', {}, label), note, sub);
    } else {                     // unions and lists: JSON text
      input = h('input', { type: 'text', value: value === undefined ? '' : JSON.stringify(value), placeholder: 'JSON',
        onchange: function (e) {
          try { set(e.target.value ? JSON.parse(e.target.value) : undefined); e.target.classList.remove('q-missing'); }
          catch (x) { e.target.classList.add('q-missing'); }
        } });
    }
    return h('label', Object.assign({ class: 'q-field' }, where), h('span', { class: 'q-label' }, label, required ? h('span', { class: 'warn' }, ' *') : null), input, note);
  }
  function field(owner, name, def, ctx) {
    return widget(def, owner[name], function (v) {
      if (v === undefined) delete owner[name]; else owner[name] = v;
      changed();
    }, name, ctx);
  }

  // ---------------------------------------------------------------- the quest form
  var listEl = h('div', { class: 'q-list' });
  var formEl = h('div', { class: 'q-form' });
  var sideEl = h('div', { class: 'q-side' });

  // "Parcel": the item the giver hands over when the quest is accepted (stage 1's reward.item), as a plain field.
  function setReward(stage, key, v) {
    var r = copy(stage.reward || {});
    if (v === undefined || v === '') delete r[key]; else r[key] = v;
    if (Object.keys(r).length) stage.reward = r; else delete stage.reward;
    changed();
  }
  function parcelField(stage, i) {
    return h('label', { class: 'q-field', 'data-q-plain': 'parcel' },
      h('span', { class: 'q-label' }, 'Item the giver hands over'),
      h('input', { type: 'text', list: 'q-list-item', value: (stage.reward || {}).item || '',
        placeholder: 'optional: pick an item, or type its resref',
        oninput: function (e) { setReward(stage, 'item', e.target.value); } }),
      h('div', { class: 'note q-hint' }, 'The parcel of a delivery: the player receives it when accepting; a later "hand an item" stage takes it.'));
  }
  // The last stage pays the reward: XP and gold per player (leave both empty for the size chosen by party level).
  function rewardFields(stage, i) {
    var num = function (key, label, hint) {
      return h('label', { class: 'q-field', 'data-q-plain': key },
        h('span', { class: 'q-label' }, label),
        h('input', { type: 'number', min: 0, value: (stage.reward || {})[key] === undefined ? '' : stage.reward[key],
          placeholder: hint,
          oninput: function (e) { setReward(stage, key, e.target.value === '' ? undefined : Number(e.target.value)); } }));
    };
    return h('div', { class: 'q-row' }, num('xp', 'Reward: XP per player', 'sized by party level'),
      num('gold', 'Reward: gold per player', 'sized by party level'));
  }

  function stageCard(stage, i) {
    var sdef = defs.StageInput;
    var kind = stage['do'] || 'talk';
    var ctx = { stageDo: kind, stageIdx: i };
    // Stage 1 is always spoken by the giver, so it has no NPC of its own to choose.
    var shown = ['journal'].concat(i === 0 ? FIRST_STAGE : [], BY_KIND[kind] || []).filter(function (k) {
      return sdef.properties[k] && !(i === 0 && k === 'to');
    });
    var move = function (to) { spec.stages.splice(to, 0, spec.stages.splice(i, 1)[0]); changed(); renderForm(); };
    var card = h('div', { class: 'card q-stage' },
      h('div', { class: 'q-row' },
        h('b', {}, 'Stage ' + (i + 1) + (i === 0 ? ' - the giver offers the quest' : '')), h('span', { class: 'q-grow' }),
        h('button', { type: 'button', disabled: i === 0, title: 'Move up', onclick: function () { move(i - 1); } }, '↑'),
        h('button', { type: 'button', disabled: i === spec.stages.length - 1, title: 'Move down', onclick: function () { move(i + 1); } }, '↓'),
        h('button', { type: 'button', title: 'Remove this stage', onclick: function () { spec.stages.splice(i, 1); changed(); renderForm(); } }, 'Remove')));
    put(card, h('label', { class: 'q-field' }, h('span', { class: 'q-label' }, LABELS['do']),
      h('select', { onchange: function (e) { stage['do'] = e.target.value; changed(); renderForm(); } },
        (sdef.properties['do']['enum'] || Object.keys(KIND_HELP)).map(function (k) {
          return h('option', { value: k, selected: k === kind }, KIND_HELP[k] || k);
        }))));
    shown.forEach(function (k) { put(card, field(stage, k, sdef.properties[k], ctx)); });
    if (i === 0) put(card, parcelField(stage, i));
    if (i === spec.stages.length - 1 && i > 0) put(card, rewardFields(stage, i));
    var more = h('details', { class: 'q-more' }, h('summary', { class: 'note' }, 'More options'));
    Object.keys(sdef.properties).forEach(function (k) {
      if (k !== 'do' && shown.indexOf(k) < 0) put(more, field(stage, k, sdef.properties[k], ctx));
    });
    return put(card, more);
  }

  function usePreset(p) {
    var hasWork = (spec.stages || []).some(function (s) { return Object.keys(clean(s)).length > 1; });
    if (hasWork && !window.confirm('Replace the stages below with the "' + p.title + '" outline?')) return;
    spec.stages = copy(p.stages);
    presetNote = PRESET_NOTE[p.id] || '';
    changed();
    renderForm();
  }

  function renderForm() {
    clear(formEl);
    var rootDef = defs.QuestInput;
    if (!rootDef) {
      put(formEl, h('div', { class: 'card' }, h('p', { class: 'err' }, 'The quest builder is not available.'),
        info.problems.map(function (p) { return h('p', {}, p); })));
      return;
    }
    put(formEl, h('h2', {}, snapshot === null ? 'New quest' : 'Quest: ' + (spec.name || '')));
    var top = h('div', { class: 'card' });
    TOP_SHOWN.forEach(function (k) { put(top, field(spec, k, rootDef.properties[k], { top: true })); });
    put(formEl, top);

    put(formEl, h('h3', {}, 'Stages'),
      h('p', { class: 'note' }, 'Start from an outline, then fill in the fields. Stage 1 is always the giver offering the quest; the last stage ends it and pays the reward.'),
      h('div', { class: 'q-presets' }, PRESETS.map(function (p) {
        return h('button', { type: 'button', title: p.blurb, onclick: function () { usePreset(p); } }, p.title);
      })),
      presetNote ? h('p', { class: 'warn' }, presetNote) : null);
    spec.stages = spec.stages || [];
    spec.stages.forEach(function (s, i) { put(formEl, stageCard(s, i)); });
    put(formEl, h('button', { type: 'button', onclick: function () { spec.stages.push({ 'do': spec.stages.length ? 'return' : 'talk', journal: '' }); changed(); renderForm(); } }, '+ Add a stage'));

    var more = h('details', { class: 'q-more' }, h('summary', { class: 'note' }, 'More quest options (tag, priority, reward)'));
    Object.keys(rootDef.properties).forEach(function (k) {
      if (TOP_SHOWN.indexOf(k) < 0 && TEMPLATE_FIELDS.indexOf(k) < 0) put(more, field(spec, k, rootDef.properties[k], {}));
    });
    put(formEl, more);
  }

  // ---------------------------------------------------------------- the list of quests
  function renderList() {
    clear(listEl);
    put(listEl, h('h2', {}, 'In this project'),
      h('button', { type: 'button', onclick: function () { leave(function () { spec = blank(); snapshot = null; plan = null; presetNote = ''; renderAll(); }); } }, '+ New quest'));
    if (!quests.length) put(listEl, h('p', { class: 'note' }, 'No quests yet.'));
    quests.forEach(function (q) {
      var row = h('div', { class: 'q-item' + (snapshot !== null && spec.tag === q.tag ? ' q-current' : '') },
        h('div', {}, q.saved ? h('a', { href: '#', onclick: function (e) { e.preventDefault(); leave(function () { open(q.tag); }); } }, q.name) : q.name),
        h('div', { class: 'note' }, q.tag, ' ',
          q.built ? h('span', { class: 'pill ok' }, 'in the module') : h('span', { class: 'pill' }, 'draft'),
          q.saved ? null : h('span', { class: 'pill', title: 'This journal quest was not made here, so it cannot be edited here.' }, 'made elsewhere')));
      put(listEl, row);
    });
  }
  function leave(then) {
    if (!dirty() || window.confirm('Discard the changes to this quest?')) then();
  }
  function open(tag) {
    get('/spec?tag=' + encodeURIComponent(tag)).then(function (d) {
      spec = d.spec;
      if (!spec.tag) spec.tag = tag;
      snapshot = JSON.stringify(clean(spec));
      plan = null;
      presetNote = '';
      renderAll();
    }).catch(fail);
  }

  // ---------------------------------------------------------------- plan, build, save, remove
  function problems() {
    var out = [];
    if (!String(spec.name || '').trim()) out.push('Give the quest a name.');
    if (!String(spec.giver || '').trim()) out.push('Choose the quest giver.');
    if (!(spec.stages || []).length) out.push('Add stages (pick an outline to start).');
    (spec.stages || []).forEach(function (s, i) {
      if (!String(s.journal || '').trim() && !s.optional) out.push('Stage ' + (i + 1) + ' needs a journal entry.');
      (REQUIRED[s['do']] || []).forEach(function (k) {
        if (s[k] === undefined || s[k] === '') out.push('Stage ' + (i + 1) + ' needs: ' + ((k === 'target' && TARGET_LABEL[s['do']]) || LABELS[k] || k) + '.');
      });
    });
    return out;
  }
  function fail(e) {
    busy = ''; plan = { ok: false, error: e.message, stage: e.stage, field: e.field };
    renderSide(); markField(e.stage, e.field);
  }
  // Outline the box a builder error is about and bring it into view.
  function markField(stage, field) {
    var prev = document.querySelectorAll('.q-bad');
    for (var i = 0; i < prev.length; i++) prev[i].classList.remove('q-bad');
    if (!field) return;
    var sel = stage ? '[data-q-stage="' + (stage - 1) + '"][data-q-field="' + field + '"]' : ':not([data-q-stage])[data-q-field="' + field + '"]';
    var box = formEl.querySelector(sel);
    if (!box) return;
    var more = box.closest('details');
    while (more) { more.open = true; more = more.parentElement && more.parentElement.closest('details'); }
    box.classList.add('q-bad');
    box.scrollIntoView({ block: 'center' });
  }
  function run(dry) {
    if (!dry && !window.confirm('Build "' + spec.name + '" into the module? The files it changes are kept in History, so it can be undone.')) return;
    busy = dry ? 'Checking the plan (reads the whole module, a few seconds)...' : 'Building...';
    renderSide();
    post(dry ? '/plan' : '/build', { spec: JSON.stringify(clean(spec)), 'new': snapshot === null ? '1' : '' }).then(function (d) {
      busy = '';
      plan = { ok: true, dry: dry, result: d.result, applied: d.applied };
      if (!dry) {
        spec.tag = d.result.tag;
        snapshot = JSON.stringify(clean(spec));
        quests = d.quests;
        renderList();
        renderForm();
      }
      renderSide();
    }).catch(fail);
  }
  function save() {
    post('/save', { spec: JSON.stringify(clean(spec)), 'new': snapshot === null ? '1' : '' }).then(function (d) {
      spec.tag = d.tag;
      snapshot = JSON.stringify(clean(spec));
      quests = d.quests;
      renderAll();
    }).catch(fail);
  }
  function remove() {
    var built = quests.some(function (q) { return q.tag === spec.tag && q.built; });
    var msg = built ? 'Remove "' + spec.name + '" from the module (journal, dialog lines, variables)? The quest stays here as a draft.'
      : 'Delete the draft "' + spec.name + '"?';
    if (!window.confirm(msg)) return;
    busy = 'Removing...';
    renderSide();
    post(built ? '/remove' : '/delete', { tag: spec.tag }).then(function (d) {
      busy = '';
      quests = d.quests;
      if (built) plan = { ok: true, removed: true, applied: d.applied, result: d.result };
      else { spec = blank(); snapshot = null; plan = null; }
      renderAll();
    }).catch(fail);
  }

  function fileList(applied) {
    if (!applied) return null;
    var out = [h('p', {}, applied.written.length + ' file(s) written' + (applied.deleted && applied.deleted.length ? ', ' + applied.deleted.length + ' deleted' : '') + (applied.unchanged ? ', ' + applied.unchanged + ' already up to date' : '') + '. ',
      h('a', { href: base.replace(/\/quests$/, '/history') }, 'History'), ' can undo them.')];
    if (applied.compile) {
      out.push(h('p', { class: applied.compile.ok ? 'ok' : 'err' }, applied.compile.checked + ' quest script(s) compiled with nwnsc before writing.'));
    } else {
      out.push(h('p', { class: 'warn' }, 'The scripts were not compile-checked here; Build module compiles them.'));
    }
    var v = applied.verify;
    if (v && v.checked) {
      var gaps = (v.gaps || []).concat((v.journal && v.journal.errors || []).map(function (e) { return e.message; }));
      out.push(v.completable && !gaps.length
        ? h('p', { class: 'ok' }, 'Checked: the quest can be completed.')
        : h('div', {}, h('p', { class: 'err' }, 'Checked: the quest cannot be completed yet:'), gaps.map(function (g) { return h('p', { class: 'err' }, String(g)); })));
      (v.journal && v.journal.warnings || []).forEach(function (w) { out.push(h('p', { class: 'warn' }, String(w.message))); });
    } else if (v) {
      out.push(h('p', { class: 'warn' }, 'The completion check did not run: ' + v.error));
    }
    out.push(h('details', {}, h('summary', { class: 'note' }, 'Files'),
      h('ul', {}, applied.written.map(function (f) { return h('li', {}, f.name, f['new'] ? ' (new)' : ''); })
        .concat((applied.deleted || []).map(function (n) { return h('li', {}, n, ' (deleted)'); })))));
    return out;
  }

  function renderSide() {
    clear(sideEl);
    if (!info.ready) {
      put(sideEl, h('div', { class: 'card' }, h('p', { class: 'err' }, 'Quests cannot be built yet:'), info.problems.map(function (p) { return h('p', {}, p); })));
    }
    (info.notes || []).forEach(function (n) { put(sideEl, h('p', { class: 'note' }, n)); });
    var todo = problems();
    var planned = plan && plan.ok && plan.dry;
    put(sideEl, h('div', { class: 'q-row' },
      h('button', { type: 'button', disabled: !info.ready || !!todo.length || !!busy, onclick: function () { run(true); } }, '1. Check the plan'),
      h('button', { type: 'button', disabled: !planned || !!busy, title: planned ? '' : 'Check the plan first', onclick: function () { run(false); } }, '2. Build into the module')),
      h('div', { class: 'q-row' },
        h('button', { type: 'button', disabled: !String(spec.name || '').trim(), title: 'Keep this quest in the project\'s quests/ folder without building it', onclick: save }, 'Save draft'),
        snapshot !== null ? h('button', { type: 'button', onclick: remove }, 'Remove') : null));
    if (busy) { put(sideEl, h('p', { class: 'note' }, busy)); return; }
    if (!plan) {
      if (todo.length) put(sideEl, h('p', {}, 'Still to fill in:'), h('ul', {}, todo.map(function (t) { return h('li', { class: 'warn' }, t); })));
      else put(sideEl, h('p', { class: 'note' }, 'Check the plan to see exactly what would be written. Nothing changes until you build.'));
      return;
    }
    if (!plan.ok) {
      put(sideEl, h('p', { class: 'err' }, plan.error),
        plan.field ? h('p', { class: 'note' }, 'The box it is about is outlined in red.') : null);
      return;
    }
    if (plan.removed) {
      put(sideEl, h('h3', {}, 'Removed from the module'), fileList(plan.applied));
      return;
    }
    var r = plan.result;
    put(sideEl, h('h3', {}, (plan.dry ? 'Plan: ' : 'Built: ') + r.name), h('div', { class: 'note' }, 'tag ' + r.tag),
      h('table', {}, h('tbody', {}, (r.stages || []).map(function (s) {
        return h('tr', {}, h('td', {}, String(s.n) + (s.end ? ' (end)' : '')), h('td', {}, s['do']), h('td', {}, s.by || ''), h('td', {}, s.journal));
      }))),
      (r.warnings || []).map(function (w) { return h('p', { class: 'warn' }, String(w)); }),
      (r.dialogs || []).map(function (d) {
        return h('details', {}, h('summary', {}, 'Dialog of ' + d.npc + (d.created ? ' (new conversation ' + d.dialog + ')' : ' (' + d.dialog + ')')),
          h('ul', {}, (d.lines || []).map(function (l) { return h('li', {}, l); })));
      }),
      (r.placed || []).map(function (p) { return h('p', { class: 'note' }, 'Placed: ' + p); }),
      (r.notes || []).map(function (n) { return h('p', { class: 'note' }, String(n)); }),
      plan.dry ? null : fileList(plan.applied),
      plan.dry ? null : h('p', {}, 'Next: ', h('a', { href: base.replace(/\/quests$/, '/') }, 'Build module'), ' to compile and download the .mod.'),
      h('details', {}, h('summary', { class: 'note' }, 'Full report'), h('pre', { class: 'log' }, JSON.stringify(r, null, 2))));
  }

  function renderAll() { renderList(); renderForm(); renderSide(); }

  // ---------------------------------------------------------------- start
  put(root, h('div', { class: 'q-layout' }, listEl, formEl, sideEl), lists);
  put(formEl, h('p', { class: 'note' }, 'Loading...'));
  window.addEventListener('beforeunload', function (e) { if (dirty()) { e.preventDefault(); e.returnValue = ''; } });
  get('/data').then(function (d) {
    info = d.info;
    defs = (d.schema && d.schema.definitions) || {};
    quests = d.quests;
    renderAll();
    return get('/contents');
  }).then(function (d) {
    var c = d.contents;
    [['creature', 'creatures'], ['item', 'items'], ['area', 'areas'], ['placeable', 'placeables'], ['waypoint', 'waypoints']].forEach(function (pair) {
      put(lists, h('datalist', { id: 'q-list-' + pair[0] }, (c[pair[1]] || []).map(function (o) {
        var extra = o.area ? ' (' + o.area + ')' : o.note ? ' (' + o.note + ')' : '';
        return h('option', { value: o.value }, o.label + extra);
      })));
    });
    return get('/base').catch(function () { return null; });   // slower (reads the game files), so after the rest
  }).then(function (d) {
    var b = d && d.base;
    if (!b) return;
    [['creature', 'creatures'], ['item', 'items']].forEach(function (pair) {
      var list = document.getElementById('q-list-' + pair[0]);
      if (!list) return;
      var seen = {};
      for (var i = 0; i < list.options.length; i++) seen[list.options[i].value.toLowerCase()] = true;
      (b[pair[1]] || []).forEach(function (r) {
        if (!seen[r]) list.appendChild(h('option', { value: r }, 'base game'));
      });
    });
  }).catch(function (e) {
    clear(formEl);
    put(formEl, h('p', { class: 'err' }, e.message));
  });
}());
