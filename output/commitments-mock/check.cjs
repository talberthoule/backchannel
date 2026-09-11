// Run: node output/commitments-mock/check.cjs [path to playwright] [--host]
// Defaults to normal module resolution; no per-machine skill path is required.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { pathToFileURL } = require('node:url');
const playwrightPath = process.argv.slice(2).find((arg) => arg !== '--host');
const { chromium } = require(playwrightPath || 'playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    if (process.argv.includes('--host')) {
      await page.setViewportSize({ width: 1024, height: 900 });
      await page.goto(pathToFileURL(join(__dirname, 'preview.html')).href);
      const frame = page.frameLocator('iframe');
      await frame.locator('#bc-list > li').first().waitFor();
      assert.equal(await frame.locator('#bc-list > li').count(), 5);
      await frame.locator('[data-id="1"][data-field="status"]').selectOption('Completed');
      assert.equal(await frame.locator('#bc-next-count').innerText(), '(4)');
      await page.setViewportSize({ width: 320, height: 900 });
      const fits = await frame.locator('#bc-commitments').evaluate((el) => el.scrollWidth <= el.clientWidth);
      assert.equal(fits, true, 'host preview overflows at 320px');
      assert.deepEqual(errors, []);
      console.log('PASS: host renderer, completion interaction, and 320px layout.');
      return;
    }
    const fragment = readFileSync(join(__dirname, 'commitments.html'), 'utf8');
    const mount = async (width, theme) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ colorScheme: theme });
      await page.setContent(`<html style="color-scheme:${theme}"><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body style="margin:0">${fragment}</body></html>`);
    };
    for (const [width, theme, name] of [[1024, 'light', 'desktop'], [360, 'light', 'mobile'], [1024, 'dark', 'desktop-dark'], [360, 'dark', 'mobile-dark']]) {
      await mount(width, theme);
      assert.equal(await page.locator('#bc-list > li').count(), 5);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${name} page overflows`);
      const overflowing = await page.locator('#bc-commitments input, #bc-commitments select, #bc-commitments button').evaluateAll((elements) => elements.filter((el) => {
        if (!el.getClientRects().length) return false;
        const rect = el.getBoundingClientRect();
        return rect.left < 0 || rect.right > innerWidth + 1;
      }).map((el) => el.outerHTML));
      assert.deepEqual(overflowing, [], `${name} controls overflow`);
      await page.screenshot({ path: join(__dirname, `${name}.png`), fullPage: true });
    }
    await mount(1024, 'light');
    await page.locator('[data-id="2"][data-field="owner"]').selectOption('Leah Foster');
    assert.doesNotMatch(await page.locator('#bc-summary').innerText(), /needs an owner/);
    await page.locator('[data-id="1"][data-field="due"]').fill('2026-09-10');
    await page.locator('[data-id="1"][data-field="due"]').press('Tab');
    assert.doesNotMatch(await page.locator('#bc-summary').innerText(), /overdue/);
    await page.locator('[data-id="1"][data-field="status"]').selectOption('Completed');
    assert.equal(await page.locator('#bc-list > li').count(), 4);
    assert.equal(await page.locator('#bc-next-count').innerText(), '(4)');
    await page.locator('[data-filter="completed"]').click();
    assert.equal(await page.locator('#bc-list > li').count(), 2);
    await page.locator('[data-id="1"][data-field="status"]').selectOption('Open');
    assert.equal(await page.locator('#bc-next-count').innerText(), '(5)');
    await page.locator('[data-scope="meeting"]').click();
    await page.locator('[data-filter="open"]').click();
    assert.equal(await page.locator('#bc-list > li').count(), 3);
    assert.equal(await page.locator('[data-id="2"][data-field="owner"]').inputValue(), 'Leah Foster');
    await page.locator('[data-source="2"]').click();
    assert.equal(await page.locator('#bc-detail-2').isVisible(), true);
    await page.locator('[data-edit="2"]').click();
    await page.locator('[data-id="2"][data-field="title"]').fill('Confirm validation owner with Leah');
    await page.locator('[data-id="2"][data-field="title"]').press('Tab');
    assert.equal(await page.locator('[data-item="2"] .bc-title').innerText(), 'Confirm validation owner with Leah');
    await page.locator('#bc-add-open').click();
    await page.locator('#bc-new-title').fill('<script>illustrative text</script>');
    await page.getByRole('button', { name: 'Add to list', exact: true }).click();
    assert.equal(await page.locator('#bc-list > li').count(), 4);
    assert.equal(await page.locator('#bc-list .bc-title').first().innerText(), '<script>illustrative text</script>');
    assert.equal(await page.locator('#bc-next-count').innerText(), '(6)');
    assert.deepEqual(errors, []);
    console.log('PASS: four viewport/theme captures; edit, complete, reopen, shared scopes, source, add, and safe text rendering.');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
