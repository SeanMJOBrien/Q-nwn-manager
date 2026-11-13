// Browser check of the console's Quests page (Playwright, real Chromium): write a quest in the form, check the plan,
// build it, see it listed, remove it.
//
//   1. start the console on a SCRATCH COPY of a project (the test builds a quest into it):
//        nwn-manager console --projects-dir <scratch> --port 8399
//   2. run:  BASE=http://127.0.0.1:8399/p/<slug> GIVER=<creature tag> OTHER=<creature tag> node tests/ui/quests_smoke.js
//      (PLAYWRIGHT_MODULE = path to a playwright install, OUT = folder for screenshots; both optional)
function loadPlaywright() {
  const candidates = [process.env.PLAYWRIGHT_MODULE, 'playwright', 'playwright-core'].filter(Boolean);
  for (const c of candidates) { try { return require(c); } catch (e) { /* try next */ } }
  console.error('Playwright not found; set PLAYWRIGHT_MODULE to its path'); process.exit(2);
}
const { chromium } = loadPlaywright();
const fs = require('fs');
const BASE = process.env.BASE;
const GIVER = process.env.GIVER;
const OTHER = process.env.OTHER;
const OUT = process.env.OUT || require('os').tmpdir() + '/nwn-manager-ui-shots';
if (!BASE || !GIVER || !OTHER) { console.error('set BASE, GIVER and OTHER (see the header of this file)'); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });

const results = [];
const check = (name, ok, extra = '') => { results.push(!!ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name} ${extra}`); };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('dialog', d => d.accept());

  await page.goto(BASE + '/quests');
  await page.waitForSelector('.q-form .q-stage', { timeout: 20000 });
  check('form shows with the default outline', await page.locator('.q-stage').count() === 3);
  check('nav has a Quests link', await page.locator('.nav a', { hasText: 'Quests' }).count() === 1);
  check('plan is disabled until the form is filled', await page.locator('button', { hasText: '1. Check the plan' }).isDisabled());
  await page.waitForFunction(() => document.querySelectorAll('#q-list-creature option').length > 0, null, { timeout: 60000 });
  check('pickers list the module\'s creatures', true);

  // U3: plain fields for the parcel, the reward and the check
  await page.locator('button', { hasText: 'Deliver' }).click();
  check('Deliver outline has a plain parcel field on stage 1', await page.locator('.q-stage').nth(0).locator('[data-q-plain=parcel] input').count() === 1);
  check('the last stage has XP and gold boxes', await page.locator('.q-stage').nth(1).locator('[data-q-plain=xp] input, [data-q-plain=gold] input').count() === 2);
  await page.locator('.q-stage').nth(0).locator('[data-q-plain=parcel] input').fill('some_parcel');
  await page.locator('.q-stage').nth(1).locator('[data-q-plain=xp] input').fill('250');
  await page.locator('button', { hasText: 'Persuade or fight' }).click();
  check('a check offers skill and difficulty drop-downs', await page.locator('.q-stage').nth(1).locator('[data-q-field=check] select').count() >= 3);
  // U4: a builder error outlines its box (a check with a skill but no difficulty or dc)
  await page.locator('button', { hasText: 'Errand' }).click();
  await page.locator('.q-form .card').first().locator('input[type=text]').nth(0).fill('Smoke Test Errand');
  await page.locator('.q-form .card').first().locator('input[type=text]').nth(1).fill(GIVER);
  const stages = page.locator('.q-stage');
  await stages.nth(0).locator('textarea').first().fill('I agreed to run an errand.');
  await stages.nth(1).locator('textarea').first().fill('I spoke to the contact.');
  await stages.nth(1).locator('input[list=q-list-creature]').first().fill(OTHER);
  await stages.nth(2).locator('textarea').first().fill('The errand is done.');
  await page.screenshot({ path: OUT + '/quests-form.png', fullPage: true });

  const checkBox = stages.nth(1).locator('[data-q-field=check]');
  await checkBox.locator('summary').click();
  const skillBox = checkBox.locator('label.q-field').filter({ has: page.locator('.q-label', { hasText: /^skill$/ }) }).locator('select');
  await skillBox.selectOption('persuade');
  await page.locator('button', { hasText: '1. Check the plan' }).click();
  await page.waitForSelector('.q-side .err', { timeout: 120000 });
  check('a builder error is shown', /dc or difficulty/.test(await page.locator('.q-side .err').innerText()));
  check('the box it is about is outlined', await stages.nth(1).locator('.q-bad[data-q-field=check]').count() === 1);
  await skillBox.selectOption('');
  const planBtn = page.locator('button', { hasText: '1. Check the plan' });
  check('plan is enabled once filled', await planBtn.isEnabled());
  await planBtn.click();
  await page.waitForSelector('.q-side h3', { timeout: 120000 });
  const planTitle = await page.locator('.q-side h3').first().innerText();
  check('plan comes back', planTitle.startsWith('Plan: Smoke Test Errand'), planTitle + ' ' + (await page.locator('.q-side .err').allInnerTexts()).join(' '));
  check('plan lists three stages', await page.locator('.q-side table tr').count() === 3);
  await page.screenshot({ path: OUT + '/quests-plan.png', fullPage: true });

  await page.locator('button', { hasText: '2. Build into the module' }).click();
  await page.waitForFunction(() => /^Built: /.test((document.querySelector('.q-side h3') || {}).innerText || ''), null, { timeout: 120000 });
  check('build reports written files', /file\(s\) written/.test(await page.locator('.q-side').innerText()));
  check('quest scripts were compile-checked', await page.locator('.q-side p.ok', { hasText: 'compiled with nwnsc' }).count() === 1);
  check('the completion check ran after the build', await page.locator('.q-side p', { hasText: 'Checked: the quest' }).count() === 1, await page.locator('.q-side p', { hasText: 'Checked:' }).allTextContents().then(function (t) { return t.join(' | '); }));
  check('the quest is listed as in the module', await page.locator('.q-item', { hasText: 'Smoke Test Errand' }).locator('.pill.ok').count() === 1);
  await page.screenshot({ path: OUT + '/quests-built.png', fullPage: true });

  await page.reload();
  await page.waitForSelector('.q-item a');
  await page.locator('.q-item a', { hasText: 'Smoke Test Errand' }).click();
  await page.waitForFunction(() => /Quest: Smoke Test Errand/.test(document.querySelector('.q-form h2').innerText));
  check('a saved quest reopens with its fields', await page.locator('.q-stage').nth(1).locator('input[list=q-list-creature]').first().inputValue() === OTHER);

  await page.locator('button', { hasText: 'Remove' }).last().click();
  await page.waitForFunction(() => /Removed from the module/.test(document.querySelector('.q-side').innerText), null, { timeout: 120000 });
  check('removed quest stays as a draft', await page.locator('.q-item', { hasText: 'Smoke Test Errand' }).locator('.pill', { hasText: 'draft' }).count() === 1);
  await page.locator('button', { hasText: 'Remove' }).last().click();
  await page.waitForFunction(() => !/Smoke Test Errand/.test(document.querySelector('.q-list').innerText), null, { timeout: 20000 });
  check('draft deleted', true);

  check('no browser errors', errors.length === 0, errors.join(' | '));
  await browser.close();
  const failed = results.filter(ok => !ok).length;
  console.log(`${results.length - failed}/${results.length} checks passed; screenshots in ${OUT}`);
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
