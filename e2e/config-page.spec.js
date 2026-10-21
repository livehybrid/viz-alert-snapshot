/*
 * Configuration page e2e: the packaged app on a real Splunk, driven through a
 * real browser.
 *
 * Every claim about what was STORED is read back through raw Splunk REST
 * (KV store data, storage/passwords) on the management port. The UI only ever
 * talks to /viz_alert/* on splunkweb, so a save that silently fails cannot be
 * confirmed by the same handler that failed it.
 */
const { test, expect, group, chooseSearch, APP } = require('./fixtures');

const RUN = Date.now().toString(36);
const S_EXISTING = `vas_e2e_existing_${RUN}`;
const S_SAVE = `vas_e2e_save_${RUN}`;
const S_INVALID = `vas_e2e_invalid_${RUN}`;
const ALL = [S_EXISTING, S_SAVE, S_INVALID];

test.beforeAll(async ({ splunk }) => {
    // The container reports healthy before the KV store does (10.6 answers 503).
    await splunk.waitForKvStore();
    for (const s of ALL) await splunk.createSavedSearch(s);
});

test.afterAll(async ({ splunk }) => {
    for (const s of ALL) {
        await splunk.kvDelete(s);
        await splunk.deleteSavedSearch(s);
    }
});

/** Splunk Web logs ambient errors on a fresh Enterprise container that have
 *  nothing to do with this app (core resources answering 404 and similar).
 *  Anything raised by the app's own bundle or endpoints is never tolerated,
 *  except the optional nav-bar logo: Splunk's chrome asks every app for
 *  static/appLogo.png and falls back to the app label when it is absent. */
const OPTIONAL_ASSET = /\/viz-alert-snapshot\/static\/appLogo(_2x)?\.png$/;
function isOurs(text, url) {
    if (OPTIONAL_ASSET.test(url || '')) return false;
    return /viz-alert-snapshot|viz_alert/.test(`${text} ${url || ''}`);
}

test('config page loads without console errors', async ({ page, configPage }) => {
    const errors = [];
    const ambient = [];
    page.on('console', (m) => {
        if (m.type() !== 'error') return;
        const loc = m.location() || {};
        const entry = `${m.text()} @ ${loc.url || '?'}`;
        if (isOurs(m.text(), loc.url) || !/Failed to load resource/.test(m.text())) errors.push(entry);
        else ambient.push(entry);
    });
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
    const failed = [];
    page.on('response', (r) => {
        if (r.status() >= 400 && isOurs('', r.url())) failed.push(`${r.status()} ${r.url()}`);
    });

    // Fresh load, so the listeners see the whole page lifecycle.
    await configPage.reload({ waitUntil: 'domcontentloaded' });
    await expect(configPage.getByRole('heading', { name: 'Visual Alerts', level: 1 })).toBeVisible();
    // The saved-search list arrived (the page's first REST call completed).
    await group(configPage, 'Saved search').locator('[data-test="select"]').click();
    await expect(configPage.locator('[data-test="option"]').filter({ hasText: S_EXISTING })).toHaveCount(1);
    await configPage.keyboard.press('Escape');
    await configPage.waitForTimeout(3000);

    if (ambient.length) console.log('ambient Splunk console noise (tolerated):\n' + ambient.join('\n'));
    expect(errors, 'console errors on the config page').toEqual([]);
    expect(failed, 'failed app requests').toEqual([]);
    await expect(configPage.locator('[data-test="message"][data-test-type="error"]')).toHaveCount(0);
});

test('existing settings display', async ({ splunk, configPage }) => {
    await splunk.kvPut({
        _key: S_EXISTING, search_name: S_EXISTING,
        viz_type: 'splunk.column', width: 1024, height: 333, theme: 'light',
        data_strategy: 'sample', post_search: '| stats count by e2e_marker',
        options: { 'e2e-option': 'seeded' }, destinations: [],
    });

    await chooseSearch(configPage, S_EXISTING);
    await expect(configPage.getByText('Loaded existing configuration from saved config.')).toBeVisible();
    await expect(group(configPage, 'Visualization').locator('[data-test="select"]')).toHaveText('Column');
    await expect(group(configPage, 'Theme').locator('[data-test="select"]')).toHaveText('Light');
    await expect(group(configPage, 'Preview data').locator('[data-test="select"]')).toHaveText('Sample data');
    const size = group(configPage, 'Size (px)').locator('input');
    await expect(size.nth(0)).toHaveValue('1024');
    await expect(size.nth(1)).toHaveValue('333');
    await expect(configPage.getByRole('textbox', { name: 'Post-search (optional)' }))
        .toHaveValue('| stats count by e2e_marker');
    await expect(configPage.getByRole('textbox', { name: 'Viz options (JSON)' })).toHaveValue(/"e2e-option": "seeded"/);
});

test('a change saves and survives a reload', async ({ splunk, configPage }) => {
    // Nothing stored yet, so a pass below cannot be a leftover.
    expect((await splunk.kvGet(S_SAVE)).status).toBe(404);

    await chooseSearch(configPage, S_SAVE);
    const width = group(configPage, 'Size (px)').locator('input').nth(0);
    await width.fill('777');
    await width.press('Tab');
    await configPage.getByRole('textbox', { name: 'Post-search (optional)' }).fill('| head 5');
    await group(configPage, 'Theme').locator('[data-test="select"]').click();
    await configPage.locator('[data-test="option"]').filter({ hasText: /^Light$/ }).click();

    await configPage.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(configPage.locator('[data-test="message"][data-test-type="success"]'))
        .toContainText(`Saved “${S_SAVE}”`);

    // The stored document, read from the KV store itself.
    await expect.poll(async () => (await splunk.kvGet(S_SAVE)).status).toBe(200);
    const { doc } = await splunk.kvGet(S_SAVE);
    expect(doc).toMatchObject({
        _key: S_SAVE, search_name: S_SAVE, width: 777, theme: 'light', post_search: '| head 5',
    });

    // And it comes back after a full reload.
    await configPage.reload({ waitUntil: 'domcontentloaded' });
    await chooseSearch(configPage, S_SAVE);
    await expect(configPage.getByText('Loaded existing configuration from saved config.')).toBeVisible();
    await expect(group(configPage, 'Size (px)').locator('input').nth(0)).toHaveValue('777');
    await expect(group(configPage, 'Theme').locator('[data-test="select"]')).toHaveText('Light');
    await expect(configPage.getByRole('textbox', { name: 'Post-search (optional)' })).toHaveValue('| head 5');
});

test('invalid viz options show a validation error and store nothing', async ({ splunk, configPage }) => {
    await chooseSearch(configPage, S_INVALID);
    await configPage.getByRole('textbox', { name: 'Viz options (JSON)' }).fill('{"broken": ');
    await configPage.getByRole('button', { name: 'Save', exact: true }).click();

    await expect(configPage.locator('[data-test="message"][data-test-type="error"]'))
        .toContainText('Options JSON invalid');
    await expect(configPage.locator('[data-test="message"][data-test-type="success"]')).toHaveCount(0);
    // The save-persists test above is the positive control for this read.
    expect((await splunk.kvGet(S_INVALID)).status).toBe(404);
});

test('channel credentials are masked and never reach the browser', async ({ splunk, page, configPage }) => {
    const CRED = 'telegram_bot_token';
    const seeded = `e2e-seeded-${RUN}-${Math.random().toString(36).slice(2)}`;
    const typed = `e2e-typed-${RUN}-${Math.random().toString(36).slice(2)}`;
    const before = await splunk.getCred(CRED);
    await splunk.setCred(CRED, seeded);
    try {
        const bodies = [];
        page.on('response', (r) => {
            bodies.push(r.text().then((t) => `${r.url()}\n${t}`).catch(() => ''));
        });
        await configPage.reload({ waitUntil: 'domcontentloaded' });
        await expect(configPage.getByRole('heading', { name: 'Visual Alerts', level: 1 })).toBeVisible();

        await configPage.getByRole('button', { name: 'Channels…' }).click();
        const modal = configPage.getByRole('dialog', { name: 'Channel credentials' });
        await expect(modal).toBeVisible();
        const input = modal.getByRole('textbox', { name: 'Telegram bot token' });
        const field = modal.locator('[data-test="control-group"]', { has: input });
        await expect(field).toContainText('configured');
        await expect(field).not.toContainText('not set');
        await expect(input).toHaveAttribute('type', 'password');
        await expect(input).toHaveValue('');
        await expect(field.locator('[data-test="password-toggle"]')).toHaveCount(0);

        // The stored secret is in no response the page received, nor in the DOM.
        const seen = (await Promise.all(bodies)).filter((b) => b.includes(seeded));
        expect(seen.map((b) => b.split('\n')[0]), 'responses carrying the secret').toEqual([]);
        expect(await configPage.content()).not.toContain(seeded);

        // A typed value stays masked, saves, and lands in storage/passwords.
        await input.fill(typed);
        await expect(input).toHaveAttribute('type', 'password');
        expect(await modal.innerText()).not.toContain(typed);
        await modal.getByRole('button', { name: 'Save', exact: true }).click();
        await expect(configPage.getByText('Channel credentials saved.')).toBeVisible();
        expect(await splunk.getCred(CRED)).toBe(typed);
    } finally {
        if (before === null) await splunk.deleteCred(CRED);
        else await splunk.setCred(CRED, before);
    }
});

test.afterEach(async ({ page }, testInfo) => {
    if (testInfo.status !== testInfo.expectedStatus) {
        const html = await page.locator('body').innerHTML().catch(() => '');
        await testInfo.attach('body.html', { body: html, contentType: 'text/html' });
    }
});
