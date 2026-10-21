/*
 * Shared fixtures for the configuration page e2e.
 *
 *  - `splunk`: a REST client on the management port (basic auth). Tests use it
 *    to seed state and to read back what the UI stored, through routes the UI
 *    never calls (raw KV store data, storage/passwords, saved/searches), so a
 *    broken save cannot be hidden by the UI's own read path agreeing with it.
 *  - `configPage`: a browser page logged in and sitting on the app's home view.
 */
const { test: base, expect, request } = require('@playwright/test');

const MGMT_URL = process.env.SPLUNK_MGMT_URL || 'https://localhost:8089';
const USER = process.env.SPLUNK_USER || 'admin';
const PASS = process.env.SPLUNK_PASSWORD || 'Changeme1!';
const APP = 'viz-alert-snapshot';
const NS = `/servicesNS/nobody/${APP}`;
const LOCALE = 'en-GB';
const HOME_PATH = `/${LOCALE}/app/${APP}/home`;

class SplunkRest {
    constructor(ctx) { this.ctx = ctx; }

    async createSavedSearch(name, search = '| makeresults count=3 | eval n=1') {
        const r = await this.ctx.post(`${NS}/saved/searches?output_mode=json`, {
            form: { name, search, 'dispatch.earliest_time': '-15m', 'dispatch.latest_time': 'now' },
        });
        if (!r.ok()) throw new Error(`create saved search ${name}: ${r.status()} ${await r.text()}`);
    }

    async deleteSavedSearch(name) {
        await this.ctx.delete(`${NS}/saved/searches/${encodeURIComponent(name)}`);
    }

    /** Block until the app's collection answers (the KV store lags splunkweb
     *  at boot; 10.6 says 503 "KV Store is initializing"). */
    async waitForKvStore(timeoutMs = 300000) {
        const deadline = Date.now() + timeoutMs;
        let last = '';
        while (Date.now() < deadline) {
            const r = await this.ctx.get(`${this.kvPath()}?output_mode=json&limit=1`);
            if (r.ok()) return;
            last = `HTTP ${r.status()} ${(await r.text()).slice(0, 160)}`;
            await new Promise((res) => setTimeout(res, 5000));
        }
        throw new Error(`KV store not ready after ${timeoutMs} ms (last: ${last})`);
    }

    kvPath(key) {
        return `${NS}/storage/collections/data/alert_viz_configs${key ? `/${encodeURIComponent(key)}` : ''}`;
    }

    /** Write a config document straight into the KV store collection. */
    async kvPut(doc) {
        const r = await this.ctx.post(`${this.kvPath()}/batch_save?output_mode=json`, {
            data: JSON.stringify([doc]),
            headers: { 'Content-Type': 'application/json' },
        });
        if (!r.ok()) throw new Error(`kv batch_save: ${r.status()} ${await r.text()}`);
    }

    /** Read a config document straight from the KV store: {status, doc}. */
    async kvGet(key) {
        const r = await this.ctx.get(`${this.kvPath(key)}?output_mode=json`);
        const text = await r.text();
        return { status: r.status(), doc: r.ok() ? JSON.parse(text) : null, text };
    }

    async kvDelete(key) {
        await this.ctx.delete(this.kvPath(key));
    }

    credPath(name) {
        return `${NS}/storage/passwords/${encodeURIComponent(`viz_alert_channel:${name}:`)}`;
    }

    /** Create or update a channel credential in storage/passwords. */
    async setCred(name, value) {
        const upd = await this.ctx.post(`${this.credPath(name)}?output_mode=json`, { form: { password: value } });
        if (upd.ok()) return;
        const cr = await this.ctx.post(`${NS}/storage/passwords?output_mode=json`, {
            form: { name, password: value, realm: 'viz_alert_channel' },
        });
        if (!cr.ok()) throw new Error(`set credential ${name}: ${cr.status()} ${await cr.text()}`);
    }

    /** The stored clear value of a channel credential, or null when absent. */
    async getCred(name) {
        const r = await this.ctx.get(`${this.credPath(name)}?output_mode=json`);
        if (r.status() === 404) return null;
        if (!r.ok()) throw new Error(`get credential ${name}: ${r.status()} ${await r.text()}`);
        const body = await r.json();
        return body.entry[0].content.clear_password;
    }

    async deleteCred(name) {
        await this.ctx.delete(this.credPath(name));
    }
}

/** Log in through the real form and land on the config page.
 *  Waits on the URL PATHNAME: the login URL itself carries
 *  ?return_to=/en-GB/app/viz-alert-snapshot/home, so a regex over the whole
 *  URL matches before the login has happened. */
async function login(page) {
    await page.goto(`/${LOCALE}/account/login?return_to=${encodeURIComponent(HOME_PATH)}`,
        { waitUntil: 'domcontentloaded' });
    await page.locator('#username').fill(USER);
    await page.locator('#password').fill(PASS);
    await page.locator('input[type="submit"][value="Sign In"], button[type="submit"]').first().click();
    await page.waitForURL((u) => u.pathname === HOME_PATH, { waitUntil: 'domcontentloaded' });
}

const test = base.extend({
    // Worker-scoped so beforeAll/afterAll can seed and clean up with it.
    splunk: [async ({}, use) => {
        const ctx = await request.newContext({
            baseURL: MGMT_URL,
            ignoreHTTPSErrors: true,
            httpCredentials: { username: USER, password: PASS },
            timeout: 120000,
        });
        await use(new SplunkRest(ctx));
        await ctx.dispose();
    }, { scope: 'worker' }],

    configPage: async ({ page }, use) => {
        await login(page);
        await expect(page.getByRole('heading', { name: 'Visual Alerts', level: 1 })).toBeVisible();
        await use(page);
    },
});

/* ---- page helpers (React UI data-test hooks + visible text) ---- */

/** The ControlGroup whose label text is exactly `label`. */
function group(scope, label) {
    return scope.locator('[data-test="control-group"]')
        .filter({ has: scope.locator('[data-test="label"]', { hasText: new RegExp(`^${escapeRe(label)}$`) }) });
}

function escapeRe(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Pick a saved search in the filterable "Saved search" select. */
async function chooseSearch(page, name) {
    await group(page, 'Saved search').locator('[data-test="select"]').click();
    await page.locator('[data-test="filter"] input, input[data-test="filter"]').first().fill(name);
    const opt = page.locator('[data-test="option"]').filter({ hasText: name }).first();
    await opt.click();
    await expect(group(page, 'Saved search').locator('[data-test="select"]')).toContainText(name);
}

module.exports = { test, expect, login, group, chooseSearch, APP, HOME_PATH };
