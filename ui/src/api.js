/*
 * api.js — typed wrappers over the app's REST surface, via @splunk/splunk-utils.
 *
 * Two kinds of endpoints:
 *  - stock Splunk REST (saved searches) — read with output_mode=json
 *  - our persistent handlers (/viz_alert/preview, /viz_alert/config) — JSON body
 */
import { app } from '@splunk/splunk-utils/config';
import { getDefaultFetchInit } from '@splunk/splunk-utils/fetch';
import { createRESTURL } from '@splunk/splunk-utils/url';

const APP = app || 'viz-alert-snapshot';

function url(endpoint, params = {}) {
    const u = new URL(createRESTURL(endpoint, { app: APP }), window.location.origin);
    Object.entries({ output_mode: 'json', ...params }).forEach(([k, v]) => {
        if (v !== undefined && v !== null) u.searchParams.append(k, String(v));
    });
    return u.toString();
}

async function asJson(resp) {
    const text = await resp.text();
    let data;
    try {
        data = text ? JSON.parse(text) : {};
    } catch (e) {
        throw new Error(`Bad JSON from ${resp.url}: ${text.slice(0, 200)}`);
    }
    if (!resp.ok) {
        throw new Error(data.error || data.messages?.[0]?.text || `HTTP ${resp.status}`);
    }
    return data;
}

/** List ALL saved searches the user can see, across every app/owner.
 *  Uses the wildcard namespace (/servicesNS/-/-/) so private searches and
 *  searches in other apps (not just this app's) all show up. */
export async function getSavedSearches(signal) {
    const init = getDefaultFetchInit();
    const u = new URL(createRESTURL('saved/searches', { app: '-', owner: '-' }), window.location.origin);
    u.searchParams.append('output_mode', 'json');
    u.searchParams.append('count', '0');
    const resp = await fetch(u.toString(), { ...init, method: 'GET', signal });
    const data = await asJson(resp);
    return (data.entry || []).map((e) => ({
        name: e.name,
        app: e.acl?.app,
        owner: e.acl?.owner,
        sharing: e.acl?.sharing,
        search: e.content?.search || '',
        scheduled: e.content?.is_scheduled === true || e.content?.is_scheduled === '1',
        earliest: e.content?.['dispatch.earliest_time'] || '-24h',
        latest: e.content?.['dispatch.latest_time'] || 'now',
    }));
}

/** Render a config to a PNG (base64) — same engine the alert fires. */
export async function previewConfig(config, signal) {
    const init = getDefaultFetchInit();
    const resp = await fetch(url('viz_alert/preview'), {
        ...init,
        method: 'POST',
        headers: { ...init.headers, 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
        signal,
    });
    return asJson(resp);
}

/** Load a saved config for a search (200 + {_key} when none exists yet). */
export async function getConfig(searchName, signal) {
    const init = getDefaultFetchInit();
    const resp = await fetch(url(`viz_alert/config/${encodeURIComponent(searchName)}`), {
        ...init,
        method: 'GET',
        signal,
    });
    return asJson(resp);
}

/** Upsert a config. */
export async function saveConfig(config, signal) {
    const init = getDefaultFetchInit();
    const resp = await fetch(url('viz_alert/config'), {
        ...init,
        method: 'POST',
        headers: { ...init.headers, 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
        signal,
    });
    return asJson(resp);
}
