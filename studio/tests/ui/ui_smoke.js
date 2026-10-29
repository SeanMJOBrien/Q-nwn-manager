// Browser smoke test for the tfn-studio web UI (Playwright, real Chromium).
//
//   1. start the server against a TFN checkout:  bin/tfn-studio serve --port 8351
//   2. run:  node tests/ui/ui_smoke.js          (BASE, OUT, PLAYWRIGHT_MODULE are optional env vars)
//
// It drives every page like a user (stamp a prefab, stage a camp, build an encounter, write a quest, pick a map
// position), fails on any console/page error or stray "null"/"[object ...]" text, and discards everything it staged.
// TFN itself is only read; staged change sets live in the studio's .studio/ directory and are discarded at the end.
function loadPlaywright() {
  const candidates = [process.env.PLAYWRIGHT_MODULE, 'playwright', 'playwright-core',
    require('os').homedir() + '/git/uoawwwBKPtelePCsql/node_modules/playwright'].filter(Boolean);
  for (const c of candidates) { try { return require(c); } catch (e) { /* try next */ } }
  console.error('Playwright not found; set PLAYWRIGHT_MODULE to its path'); process.exit(2);
}
const { chromium } = loadPlaywright();
const fs = require('fs');
const BASE = process.env.BASE || 'http://127.0.0.1:8351';
const OUT = process.env.OUT || require('os').tmpdir() + '/tfn-studio-ui-shots';
fs.mkdirSync(OUT, { recursive: true });

const results = [];
const errors = [];
const created = [];
const check = (name, ok, extra = '') => { results.push({ name, ok: !!ok, extra }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name} ${extra}`); };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 950 } });
  const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('requestfailed', r => errors.push('requestfailed: ' + r.url()));
  page.on('response', r => { if (r.status() >= 400 && !r.url().includes('/api/specs/')) errors.push(`HTTP ${r.status()} ${r.url()}`); });
  const shot = async n => page.screenshot({ path: `${OUT}/${n}.png` });
  const noJunk = async (label) => {
    const bad = await page.evaluate(() => {
      const t = document.body.innerText;
      const found = [];
      if (/\[object /.test(t)) found.push('[object ...]');
      if (/(^|\n)null(\n|$)/.test(t)) found.push('null');
      if (/(^|\n)undefined(\n|$)/.test(t)) found.push('undefined');
      return found;
    });
    check(`${label}: no stray null/[object] text`, bad.length === 0, JSON.stringify(bad));
  };
  const discard = async id => {
    const token = await page.evaluate(async () => (await (await fetch('/api/session')).json()).token);
    const r = await page.evaluate(async ([id, token]) => (await fetch(`/api/changes/${id}/discard`, { method: 'POST', headers: { 'X-Studio-Token': token, 'Content-Type': 'application/json' }, body: '{}' })).status, [id, token]);
    check(`cleanup: discarded ${id}`, r === 200);
  };

  // ---- dashboard
  await page.goto(BASE + '/');
  await page.waitForSelector('.cards', { timeout: 20000 });
  check('dashboard renders cards', (await page.locator('.cards .card').count()) >= 3);
  await noJunk('dashboard');

  // ---- manual: dashboard card, context-aware top-bar links, the page served by the studio and straight from the file system
  const watch = (pg, label) => {
    pg.on('console', m => { if (['error', 'warning'].includes(m.type())) errors.push(`${label} console: ${m.text()}`); });
    pg.on('pageerror', e => errors.push(`${label} pageerror: ${e.message}`));
    pg.on('requestfailed', r => errors.push(`${label} requestfailed: ${r.url()}`));
    pg.on('response', r => { if (r.status() >= 400) errors.push(`${label} HTTP ${r.status()} ${r.url()}`); });
  };
  check('dashboard: Manual card links to /manual', (await page.locator('.cards a.card[href="/manual"]').count()) === 1);
  check('dashboard: top-bar Manual link points at the dashboard section',
    (await page.locator('header.top a.manual-link').getAttribute('href')) === '/manual#6-dashboard');
  for (const [pagePath, section] of [['/spawns', '8-spawn-designer'], ['/quests', '9-quest-builder'], ['/changes', '10-changes-review-apply-undo']]) {
    await page.goto(BASE + pagePath);
    await page.waitForSelector('header.top .meta .mono');      // the top bar is complete once /api/session has answered
    check(`${pagePath}: Manual link opens its manual section`, (await page.locator('header.top a.manual-link').getAttribute('href')) === `/manual#${section}`);
  }
  const [manual] = await Promise.all([ctx.waitForEvent('page'), page.locator('header.top a.manual-link').click()]);
  watch(manual, 'manual (served)');
  await manual.waitForSelector('main h1');
  check('manual opens in a new tab at the Changes section', manual.url().endsWith('/manual#10-changes-review-apply-undo'), manual.url());
  await manual.waitForTimeout(400);                          // a deep link jumps (no animation on load)
  const m = await manual.evaluate(() => ({
    toc: document.querySelectorAll('.toc a').length, tables: document.querySelectorAll('main table').length,
    copy: document.querySelectorAll('.code .copy').length, studioLink: !document.getElementById('open-studio').hidden,
    active: (document.querySelector('.toc a[aria-current="true"]') || {}).textContent || '',
    inView: (() => { const r = document.getElementById('10-changes-review-apply-undo').getBoundingClientRect(); return r.top >= 0 && r.top < 220; })(),
  }));
  check('manual: contents sidebar lists the sections', m.toc >= 30, String(m.toc));
  check('manual: tables and copy buttons are present', m.tables >= 8 && m.copy >= 10, `${m.tables} tables, ${m.copy} copy buttons`);
  check('manual: "Open the studio" link is shown when served by the studio', m.studioLink);
  check('manual: the linked section is in view', m.inView);
  check('manual: sidebar highlights the linked section', m.active.startsWith('10.'), m.active);
  await manual.locator('.toc a', { hasText: '15. Troubleshooting' }).click();
  await manual.waitForTimeout(700);
  check('manual: a contents link jumps to its section', (await manual.evaluate(() => location.hash)) === '#15-troubleshooting');
  await manual.locator('.code').first().hover();
  check('manual: copy button appears on a code block', await manual.locator('.code .copy').first().isVisible());
  await manual.close();
  const file = await ctx.newPage();
  watch(file, 'manual (file)');
  await file.goto('file://' + require('path').resolve(__dirname, '..', '..', 'MANUAL.html'));
  await file.waitForSelector('main h1');
  const f = await file.evaluate(() => ({
    toc: document.querySelectorAll('.toc a').length, copy: document.querySelectorAll('.code .copy').length,
    studioLink: !document.getElementById('open-studio').hidden, overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  }));
  check('manual from file://: renders with sidebar and copy buttons (no server needed)', f.toc >= 30 && f.copy >= 10, JSON.stringify(f));
  check('manual from file://: no "Open the studio" link (there is no studio)', !f.studioLink);
  check('manual from file://: no horizontal overflow', !f.overflow);
  await file.close();
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const mobile = await phone.newPage();
  watch(mobile, 'manual (phone)');
  await mobile.goto(BASE + '/manual');
  await mobile.waitForSelector('main h1');
  check('manual on a phone: no horizontal overflow, sidebar hidden',
    await mobile.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth && getComputedStyle(document.querySelector('.toc')).display === 'none'));
  await phone.close();

  // ---- camp builder
  await page.goto(BASE + '/camps#area=mantle');
  await page.waitForFunction(() => document.querySelector('.maphud') && /scale/.test(document.querySelector('.maphud').textContent), null, { timeout: 30000 });
  check('camps: area loaded into map', true);
  await noJunk('camps (empty plan)');
  // single prop placement + undo
  await page.locator('.tabs button', { hasText: 'Props' }).click();
  await page.locator('input[placeholder^="Search"]').first().fill('barrel');
  await page.waitForTimeout(300);
  await page.locator('.list .item').first().click();
  const box = await page.locator('.mapwrap canvas').boundingBox();
  await page.mouse.move(box.x + 300, box.y + 200);
  await page.mouse.click(box.x + 300, box.y + 200);
  await page.waitForTimeout(300);
  let chips = await page.locator('h2:has-text("Plan objects") + div .chip').allTextContents();
  check('camps: single prop placed', chips.some(c => /1 placeable/.test(c)), JSON.stringify(chips));
  await page.keyboard.press('Escape');
  await page.keyboard.press('Control+z');
  await page.waitForTimeout(200);
  chips = await page.locator('h2:has-text("Plan objects") + div .chip').allTextContents();
  check('camps: undo removes it', chips.length === 0, JSON.stringify(chips));
  // base-game creature (mined from real TFN instances)
  await page.locator('.tabs button', { hasText: 'Creatures' }).click();
  await page.locator('.chip', { hasText: 'base-game' }).click();
  await page.locator('input[placeholder^="Search creatures"]').fill('guard');
  await page.waitForTimeout(300);
  check('camps: base-game creatures listed', (await page.locator('.list .item').count()) > 0);
  await page.locator('.list .item').first().click();
  await page.mouse.move(box.x + 350, box.y + 250);
  await page.mouse.click(box.x + 350, box.y + 250);
  await page.waitForTimeout(300);
  chips = await page.locator('h2:has-text("Plan objects") + div .chip').allTextContents();
  check('camps: base-game creature placed', chips.some(c => /1 creature/.test(c)), JSON.stringify(chips));
  await page.keyboard.press('Escape');
  await page.keyboard.press('Control+z');
  await page.waitForTimeout(200);
  // prefab stamp
  await page.locator('.tabs button', { hasText: 'Prefabs' }).click();
  await page.locator('.list .item', { hasText: 'Bandit camp (random spawns)' }).first().click();
  await page.locator('button:has-text("Find open ground")').click();
  await page.waitForSelector('button:has-text("here")', { timeout: 10000 });
  await page.locator('button:has-text("here")').click();
  await page.waitForTimeout(400);
  chips = await page.locator('h2:has-text("Plan objects") + div .chip').allTextContents();
  check('camps: stamping on found open ground raises no walkability warning', (await page.locator('text=non-walkable ground').count()) === 0);
  check('camps: prefab stamped (13 props + 4 markers)', chips.some(c => /13 placeable/.test(c)) && chips.some(c => /4 marker/.test(c)), JSON.stringify(chips));
  check('camps: stage disabled until title + encounter chosen', await page.locator('button:has-text("Stage changes")').isDisabled());
  await page.locator('.pane-right select').nth(1).selectOption('bandit_moderate');
  await page.locator('input[placeholder^="e.g. Wolf den"]').fill('UI smoke camp');
  await page.waitForTimeout(250);
  check('camps: stage enabled after title + encounter', await page.locator('button:has-text("Stage changes")').isEnabled());
  await noJunk('camps (stamped)');
  await shot('03_camps_stamped');
  await page.locator('button:has-text("Stage changes")').click();
  await page.waitForSelector('a:has-text("Review & apply")', { timeout: 60000 });
  let href = await page.locator('a:has-text("Review & apply")').getAttribute('href');
  created.push(href.split('#')[1]);
  check('camps: staged via UI with no errors', (await page.locator('.pane-right .badge.error').count()) === 0, href);
  await shot('04_camps_staged');
  // save the plan's objects as a custom prefab (file is removed again below)
  await page.locator('button:has-text("Save as prefab")').click();
  await page.locator('.modal input[placeholder^="prefab id"]').fill('ui_smoke_prefab');
  await page.locator('.modal button:has-text("Save")').click();
  await page.waitForSelector('text=Saved prefab "ui_smoke_prefab"', { timeout: 10000 });
  const pfPath = require('path').join(__dirname, '..', '..', 'prefabs', 'ui_smoke_prefab.json');
  check('camps: prefab saved to prefabs/', fs.existsSync(pfPath));
  if (fs.existsSync(pfPath)) fs.unlinkSync(pfPath);

  // ---- camp builder: random camp (a camp that appears only sometimes, at one of several hand-placed spots)
  await page.goto(BASE + '/camps?fresh=random-camp#area=mantle');      // a different URL: a real reload, not a hash change with the old plan
  await page.waitForFunction(() => document.querySelector('.maphud') && /scale/.test(document.querySelector('.maphud').textContent), null, { timeout: 30000 });
  const rbox = await page.locator('.mapwrap canvas').boundingBox();
  await page.locator('.tabs button', { hasText: 'Props' }).click();
  await page.locator('input[placeholder^="Search"]').first().fill('barrel');
  await page.waitForTimeout(300);
  await page.locator('.list .item').first().click();
  await page.mouse.move(rbox.x + 300, rbox.y + 200);
  await page.mouse.click(rbox.x + 300, rbox.y + 200);
  await page.keyboard.press('Escape');
  await page.locator('.tabs button', { hasText: 'Creatures' }).click();
  await page.locator('.chip', { hasText: 'base-game' }).click();
  await page.locator('input[placeholder^="Search creatures"]').fill('guard');
  await page.waitForTimeout(300);
  await page.locator('.list .item').first().click();
  await page.mouse.move(rbox.x + 340, rbox.y + 240);
  await page.mouse.click(rbox.x + 340, rbox.y + 240);
  await page.keyboard.press('Escape');
  await page.locator('input[placeholder^="e.g. Wolf den"]').fill('UI random camp');
  check('random camp: panel is there and off by default', (await page.locator('#camp-event-on').count()) === 1 && !(await page.locator('#camp-event-on').isChecked()));
  await page.locator('#camp-event-on').check();
  await page.waitForSelector('#camp-chance', { timeout: 30000 });
  check('random camp: shows the chance per refresh', /About \d+(\.\d+)?% of area refreshes/.test(await page.locator('#camp-chance').innerText()), await page.locator('#camp-chance').innerText());
  check('random camp: no spots yet means the design location', (await page.locator('.spot-row').count()) === 0);
  await page.locator('#camp-add-spot').click();
  for (const [dx, dy] of [[300, 150], [600, 200], [450, 450]]) {
    await page.mouse.move(rbox.x + dx, rbox.y + dy);
    await page.mouse.click(rbox.x + dx, rbox.y + dy);
    await page.waitForTimeout(150);
  }
  await page.keyboard.press('Escape');
  check('random camp: three spots added with the spot tool', (await page.locator('.spot-row').count()) === 3, String(await page.locator('.spot-row').count()));
  await page.waitForFunction(() => /per spot/.test((document.querySelector('#camp-info') || {}).textContent || ''), null, { timeout: 30000 });
  check('random camp: chance is split per spot', /per spot/.test(await page.locator('#camp-info').innerText()));
  await page.locator('.spot-row input[aria-label="spot 2 facing"]').fill('135');
  await page.waitForTimeout(500);
  check('random camp: a spot\'s direction is editable', (await page.locator('.spot-row input[aria-label="spot 2 facing"]').inputValue()) === '135');
  if (await page.locator('#camp-suggest').isEnabled()) {
    const before = await page.locator('.spot-row').count();
    await page.locator('#camp-suggest').click();
    await page.waitForFunction(n => document.querySelectorAll('.spot-row').length > n, before, { timeout: 30000 }).catch(() => {});
    check('random camp: Suggest adds spots on open ground', (await page.locator('.spot-row').count()) > before);
  } else check('random camp: Suggest needs the walkmesh (disabled without game data)', true);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);
  await shot('10_camps_random');
  check('random camp: stage is allowed', await page.locator('button:has-text("Stage changes")').isEnabled());
  await noJunk('camps (random camp)');
  await page.locator('button:has-text("Stage changes")').click();
  await page.waitForSelector('a:has-text("Review & apply")', { timeout: 90000 });
  href = await page.locator('a:has-text("Review & apply")').getAttribute('href');
  created.push(href.split('#')[1]);
  check('random camp: staged via UI with no errors', (await page.locator('.pane-right .badge.error').count()) === 0, href);
  const rid = href.split('#')[1];
  const ev = await page.evaluate(async id => {
    const sum = await (await fetch(`/api/changes/${id}`)).json();
    const nss = sum.files.find(f => /\/eve_ui_rand_[0-9a-f]{4}\.nss$/.test(f.rel));      // long plan ids get a hash suffix
    const git = sum.files.find(f => f.rel.endsWith('.git.json'));
    const text = nss ? (await (await fetch(`/api/changes/${id}/diff?file=${encodeURIComponent(nss.rel)}`)).json()).diff : '';
    const gtext = git ? (await (await fetch(`/api/changes/${id}/diff?file=${encodeURIComponent(git.rel)}`)).json()).diff : '';
    return { files: sum.files.map(f => f.rel), text, gtext };
  }, rid);
  check('random camp: an event script was generated', ev.files.some(f => /src\/nss\/eve_ui_rand_[0-9a-f]{4}\.nss$/.test(f)), JSON.stringify(ev.files));
  check('random camp: the script name placeholder shows the real default', /^eve_ui_rand_[0-9a-f]{4}$/.test(await page.locator('#camp-script').getAttribute('placeholder')));
  check('random camp: the script builds the camp at one of the spots', /switch \(Random\(\d+\)\)/.test(ev.text) && /CampSpot3/.test(ev.text) && /tfn-studio camp event: plan ui_random_camp/.test(ev.text));
  const added = ev.gtext.split('\n').filter(l => l.startsWith('+'));
  check('random camp: the area file gets no props or creatures of the camp', !added.some(l => /"Bearing"|"FactionID"/.test(l)), '');
  check('random camp: the area file gets the event wiring', added.some(l => /event1|event\d/.test(l)));

  // ---- changes
  await page.goto(BASE + href);
  await page.waitForSelector('.badge.good, .badge.error', { timeout: 90000 });
  check('changes: validation passes', (await page.locator('.badge.good').count()) > 0);
  await page.locator('tr.clickable').first().click();
  await page.waitForSelector('.diff', { timeout: 20000 });
  check('changes: diff view renders', (await page.locator('.diff .add').count()) > 10);
  await noJunk('changes');

  // ---- spawn designer: edit existing, then create new
  await page.goto(BASE + '/spawns');
  await page.waitForSelector('.pane-left .list .item');
  await noJunk('spawns (new)');
  await page.locator('.pane-left .list .item', { hasText: 'bandit_moderate' }).first().click();
  await page.waitForSelector('text=Expected / refresh', { timeout: 20000 });
  check('spawns: existing ute loaded with preview', (await page.locator('table tr').count()) > 3);
  await page.locator('button:has-text("New encounter")').click();
  await page.locator('input[placeholder^="encounter resref"]').fill('ui_smoke_enc');
  await page.locator('input[placeholder^="Search creatures"]').fill('wolf');
  await page.waitForTimeout(300);
  await page.locator('.pane-center .list .item').first().click();
  await page.locator('input[placeholder^="Search creatures"]').fill('dire');
  await page.waitForTimeout(300);
  await page.locator('.pane-center .list .item').first().click();
  await page.locator('.pane-center select').nth(1).selectOption('unique');
  await page.waitForSelector('text=Expected / refresh', { timeout: 20000 });
  check('spawns: new encounter preview', (await page.locator('.pane-center table tr').count()) >= 4);
  await shot('06_spawns');
  await page.locator('button:has-text("Stage changes")').click();
  await page.waitForSelector('a:has-text("Review & apply")', { timeout: 60000 });
  href = await page.locator('a:has-text("Review & apply")').getAttribute('href');
  created.push(href.split('#')[1]);
  check('spawns: new encounter staged with no errors', (await page.locator('.badge.error').count()) === 0, href);

  // ---- quest builder: saved example
  await page.goto(BASE + '/quests#quest=q_example_wolves');
  await page.waitForSelector('text=kill alpha_wolf', { timeout: 20000 });
  check('quests: saved example loaded (4 stages)', (await page.locator('.stage-card').count()) === 4);
  await noJunk('quests (example)');
  await shot('07_quests');
  await page.locator('button:has-text("Pick on map")').first().click();
  await page.waitForSelector('.modal canvas', { timeout: 20000 });
  await page.waitForTimeout(600);
  const mbox = await page.locator('.modal canvas').boundingBox();
  await page.mouse.click(mbox.x + mbox.width / 2, mbox.y + mbox.height / 2);
  await shot('09_quests_picker');
  await page.locator('.modal button:has-text("Use this spot")').click();
  await page.waitForTimeout(300);
  check('quests: map picker updates coordinates', (await page.locator('input[type=number]').first().inputValue()) !== '');

  // ---- quest builder: brand new quest from a blank form
  await page.goto(BASE + '/quests');
  await page.waitForSelector('.stage-card');
  await page.locator('input[maxlength="27"]').fill('q_ui_smoke');
  await page.locator('input[placeholder^="e.g. Wolves"]').fill('UI Smoke Quest');
  await page.locator('input[placeholder="new NPC resref"]').fill('ui_smoke_npc');
  await page.locator('input[placeholder="e.g. Hunter Marek"]').fill('Smoke Giver');
  const areas = page.locator('.stage-card textarea');
  await areas.nth(0).fill('The giver wants a thing done.');
  await areas.nth(1).fill('Please do the thing for me.');
  await areas.nth(2).fill('The thing is done; the giver paid you.');
  await areas.nth(3).fill('Thank you, here is your pay.');
  await page.locator('details summary').last().click();
  await page.locator('details').last().locator('input[type=number]').nth(1).fill('50');
  await page.waitForTimeout(500);
  check('quests: mechanism plan for blank form', (await page.locator('.pane-right .stage-num').count()) === 2);
  await noJunk('quests (new)');
  await page.locator('button:has-text("Stage changes")').click();
  await page.waitForSelector('a:has-text("Review & apply")', { timeout: 90000 });
  href = await page.locator('a:has-text("Review & apply")').getAttribute('href');
  created.push(href.split('#')[1]);
  check('quests: new quest staged with no errors', (await page.locator('.pane-right .badge.error').count()) === 0, href);
  await shot('08_quests_staged');
  await page.locator('summary', { hasText: 'Dialog ui_smoke_npc' }).click();
  check('quests: dialog outline shown', (await page.locator('pre.outline').innerText()).includes('dlg_q_adv'));

  for (const id of created) await discard(id);
  await browser.close();
  const failed = results.filter(r => !r.ok);
  console.log('\nconsole/page errors:', errors.length ? errors : 'none');
  console.log(`${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length || errors.length ? 1 : 0);
})().catch(e => { console.error('SCRIPT ERROR', e); process.exit(2); });
