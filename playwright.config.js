// Playwright e2e of the configuration page against the docker Splunk (CI).
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
    testDir: './e2e',
    timeout: 240000,
    expect: { timeout: 60000 },
    // One Splunk, shared state (KV store, storage/passwords): run serially.
    workers: 1,
    fullyParallel: false,
    retries: 0,
    outputDir: 'e2e-results',
    use: {
        baseURL: process.env.SPLUNK_WEB_URL || 'http://localhost:8000',
        ignoreHTTPSErrors: true,
        navigationTimeout: 120000,
        actionTimeout: 60000,
        screenshot: 'only-on-failure',
        trace: 'retain-on-failure',
    },
    reporter: [['list']],
});
