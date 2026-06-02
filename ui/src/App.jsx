/*
 * App.jsx — Visual Alerts configuration UI.
 *
 * Point a saved search at a Splunk visualization, optionally post-process, preview
 * the exact image that will be sent, choose destinations (email / Telegram / Slack
 * / webhook), test-send, and save. Splunk React UI components.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import Heading from '@splunk/react-ui/Heading';
import P from '@splunk/react-ui/Paragraph';
import Card from '@splunk/react-ui/Card';
import ControlGroup from '@splunk/react-ui/ControlGroup';
import Select from '@splunk/react-ui/Select';
import Text from '@splunk/react-ui/Text';
import NumberInput from '@splunk/react-ui/Number';
import Button from '@splunk/react-ui/Button';
import Message from '@splunk/react-ui/Message';
import WaitSpinner from '@splunk/react-ui/WaitSpinner';
import Table from '@splunk/react-ui/Table';
import Modal from '@splunk/react-ui/Modal';
import Switch from '@splunk/react-ui/Switch';

import {
    getSavedSearches, getConfig, saveConfig, previewConfig, getSettings, saveSettings, testSend,
    enableAlertAction,
} from './api';

const VIZ_TYPES = [
    ['splunk.line', 'Line'], ['splunk.area', 'Area'], ['splunk.column', 'Column'],
    ['splunk.bar', 'Bar'], ['splunk.pie', 'Pie'], ['splunk.singlevalue', 'Single Value'],
    ['splunk.table', 'Table'], ['splunk.markdown', 'Markdown'],
];

const DEFAULT_CONFIG = {
    viz_type: 'splunk.line', width: 800, height: 450, theme: 'dark',
    data_strategy: 'search', post_search: '', options: {}, destinations: [],
};

const CRED_LABELS = {
    telegram_bot_token: 'Telegram bot token',
    slack_bot_token: 'Slack bot token (xoxb-…)',
};

const SIDEBAR_W = 380;

/* Build an initial config from native alert-action params (fallback when there's
   no saved Visual Alerts config in the KV store yet). */
function configFromParams(p = {}) {
    let options = {};
    try { options = JSON.parse(p.options || '{}'); } catch (e) { /* ignore */ }
    const destinations = p.to ? [{ type: 'email', to: p.to }] : [];
    return {
        ...DEFAULT_CONFIG,
        viz_type: p.viz_type || 'splunk.line',
        width: +(p.width || 800), height: +(p.height || 450),
        theme: p.theme || 'dark', post_search: p.post_search || '',
        options, destinations,
    };
}

/* A capped, scrollable results table (raw or post-processed). */
function ResultsTable({ title, data }) {
    if (!data || !(data.rows || []).length) return null;
    return (
        <div style={{ marginTop: 16 }}>
            <Heading level={4}>
                {title} <span style={{ opacity: 0.6, fontWeight: 'normal' }}>({data.total} rows)</span>
            </Heading>
            <div style={{ maxHeight: 200, overflow: 'auto', border: '1px solid #3c444d', borderRadius: 4 }}>
                <Table stripeRows>
                    <Table.Head>
                        {data.fields.map((f) => <Table.HeadCell key={f}>{f}</Table.HeadCell>)}
                    </Table.Head>
                    <Table.Body>
                        {data.rows.map((r, i) => (
                            <Table.Row key={i}>
                                {data.fields.map((f) => <Table.Cell key={f}>{String(r[f] ?? '')}</Table.Cell>)}
                            </Table.Row>
                        ))}
                    </Table.Body>
                </Table>
            </div>
        </div>
    );
}

export default function App() {
    const [searches, setSearches] = useState([]);
    const [selected, setSelected] = useState('');
    const [config, setConfig] = useState(DEFAULT_CONFIG);
    const [optionsText, setOptionsText] = useState('{}');
    const [preview, setPreview] = useState(null);
    const [channels, setChannels] = useState([]);
    const [credsSet, setCredsSet] = useState({});
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [tokenInputs, setTokenInputs] = useState({});
    const [loading, setLoading] = useState(false);
    const [previewing, setPreviewing] = useState(false);
    const [saving, setSaving] = useState(false);
    const [attachAction, setAttachAction] = useState(true);
    const [testing, setTesting] = useState(null);
    const [error, setError] = useState(null);
    const [notice, setNotice] = useState(null);
    const previewAbort = useRef(null);
    const channelsBtn = useRef(null);

    useEffect(() => {
        const ctrl = new AbortController();
        getSavedSearches(ctrl.signal).then(setSearches)
            .catch((e) => setError(`Could not load saved searches: ${e.message}`));
        getSettings(ctrl.signal)
            .then((s) => { setChannels(s.channels || []); setCredsSet(s.creds_set || {}); })
            .catch(() => { /* optional */ });
        return () => ctrl.abort();
    }, []);

    const onSelectSearch = useCallback((e, { value }) => {
        setSelected(value); setPreview(null); setNotice(null); setError(null);
        if (!value) return;
        const meta = searches.find((s) => s.name === value);
        setLoading(true);
        getConfig(value)
            .then((doc) => {
                const hasKv = doc && (doc.viz_type || (doc.destinations || []).length || doc.post_search);
                let base = DEFAULT_CONFIG;
                let from = null;
                if (hasKv) { base = { ...DEFAULT_CONFIG, ...doc }; from = 'saved config'; }
                else if (meta?.hasAction) { base = configFromParams(meta.actionParams); from = 'alert action'; }
                const merged = {
                    ...base, search_name: value, _key: value,
                    search_app: meta?.app, search_owner: meta?.owner,
                };
                setConfig(merged);
                setOptionsText(JSON.stringify(merged.options || {}, null, 2));
                if (from) setNotice(`Loaded existing configuration from ${from}.`);
            })
            .catch((e2) => setError(`Could not load config: ${e2.message}`))
            .finally(() => setLoading(false));
    }, [searches]);

    const setField = (k) => (e, { value }) => setConfig((c) => ({ ...c, [k]: value }));

    const addDest = (type) => setConfig((c) => ({ ...c, destinations: [...(c.destinations || []), { type }] }));
    const setDest = (idx, field, value) => setConfig((c) => {
        const d = [...(c.destinations || [])];
        d[idx] = { ...d[idx], [field]: value };
        return { ...c, destinations: d };
    });
    const removeDest = (idx) => setConfig((c) => ({
        ...c, destinations: (c.destinations || []).filter((_, i) => i !== idx),
    }));

    const parsedOptions = () => {
        try { return [JSON.parse(optionsText || '{}'), null]; }
        catch (e) { return [null, `Options JSON invalid: ${e.message}`]; }
    };

    const currentConfig = () => {
        const [opts, optErr] = parsedOptions();
        if (optErr) throw new Error(optErr);
        return {
            _key: selected, search_name: selected,
            search_app: config.search_app, search_owner: config.search_owner,
            post_search: config.post_search || '', viz_type: config.viz_type,
            width: Number.isFinite(+config.width) ? +config.width : 800,
            height: Number.isFinite(+config.height) ? +config.height : 450,
            theme: config.theme, data_strategy: config.data_strategy,
            options: opts, destinations: config.destinations || [],
        };
    };

    const onPreview = useCallback(() => {
        setError(null); setNotice(null);
        let cfg;
        try { cfg = currentConfig(); } catch (e) { setError(e.message); return; }
        if (previewAbort.current) previewAbort.current.abort();
        previewAbort.current = new AbortController();
        setPreviewing(true);
        previewConfig(cfg, previewAbort.current.signal)
            .then(setPreview)
            .catch((e) => setError(`Preview failed: ${e.message}`))
            .finally(() => setPreviewing(false));
    }, [config, optionsText, selected]);

    const onSave = useCallback(() => {
        setError(null);
        let cfg;
        try { cfg = currentConfig(); } catch (e) { setError(e.message); return; }
        setSaving(true);
        saveConfig(cfg)
            .then(() => {
                if (!attachAction) {
                    setNotice(`Saved configuration for “${selected}”.`);
                    return null;
                }
                return enableAlertAction(selected, config.search_app, config.search_owner)
                    .then(() => setNotice(`Saved “${selected}” and attached the alert action.`))
                    .catch((e) => setNotice(
                        `Saved “${selected}”, but couldn't attach the action (${e.message}). `
                        + 'Add "Render Viz & Notify" to the alert manually.'));
            })
            .catch((e) => setError(`Save failed: ${e.message}`))
            .finally(() => setSaving(false));
    }, [config, optionsText, selected, attachAction]);

    const onTest = (idx) => {
        setError(null); setNotice(null);
        let cfg;
        try { cfg = currentConfig(); } catch (e) { setError(e.message); return; }
        const dest = (cfg.destinations || [])[idx];
        if (!dest) return;
        setTesting(idx);
        testSend({ ...cfg, destinations: [dest] })
            .then((res) => {
                const r = (res.results || [])[0] || {};
                if (r.ok) setNotice(`Test → ${r.type} (${r.target || ''}): ${r.detail}`);
                else setError(`Test → ${r.type || dest.type} failed: ${r.detail || 'unknown error'}`);
            })
            .catch((e) => setError(`Test send failed: ${e.message}`))
            .finally(() => setTesting(null));
    };

    const credKeys = Array.from(new Set(channels.flatMap((c) => c.cred_keys || [])));

    const onSaveTokens = () => {
        saveSettings(tokenInputs)
            .then((res) => {
                setCredsSet(res.creds_set || {});
                setTokenInputs({});
                setSettingsOpen(false);
                setNotice('Channel credentials saved.');
            })
            .catch((e) => setError(`Saving credentials failed: ${e.message}`));
    };

    return (
        <div style={{ padding: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                    <Heading level={1}>Visual Alerts</Heading>
                    <P>Point a saved search at a visualization, preview the exact image that will be sent,
                        and deliver it to your channels.</P>
                </div>
                <Button elementRef={channelsBtn} label="Channels…" onClick={() => setSettingsOpen(true)} />
            </div>

            {error && (
                <div style={{ margin: '16px 0' }}>
                    <Message appearance="fill" type="error" onRequestRemove={() => setError(null)}>{error}</Message>
                </div>
            )}
            {notice && (
                <div style={{ margin: '16px 0' }}>
                    <Message appearance="fill" type="success" onRequestRemove={() => setNotice(null)}>{notice}</Message>
                </div>
            )}

            <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                {/* Fixed-width left sidebar */}
                <div style={{ flex: `0 0 ${SIDEBAR_W}px`, width: SIDEBAR_W, maxWidth: '100%' }}>
                    <Card style={{ padding: 16, width: '100%', boxSizing: 'border-box' }}>
                        <Heading level={3}>Source &amp; visualization</Heading>
                        <ControlGroup label="Saved search">
                            <Select value={selected} onChange={onSelectSearch} filter>
                                <Select.Option label="Select a saved search…" value="" />
                                {[...searches].sort((a, b) => a.name.localeCompare(b.name)).map((s) => (
                                    <Select.Option key={`${s.app}/${s.owner}/${s.name}`}
                                        label={`${s.hasAction ? '✓ ' : ''}${s.name}  ·  ${s.app}`} value={s.name} />
                                ))}
                            </Select>
                        </ControlGroup>
                        {loading && <WaitSpinner size="medium" />}
                        <ControlGroup label="Visualization">
                            <Select value={config.viz_type} onChange={setField('viz_type')}>
                                {VIZ_TYPES.map(([v, l]) => <Select.Option key={v} label={l} value={v} />)}
                            </Select>
                        </ControlGroup>
                        <ControlGroup label="Size (px)">
                            <NumberInput value={+config.width} onChange={setField('width')} min={120} max={2000} />
                            <NumberInput value={+config.height} onChange={setField('height')} min={120} max={2000} />
                        </ControlGroup>
                        <ControlGroup label="Theme">
                            <Select value={config.theme} onChange={setField('theme')}>
                                <Select.Option label="Dark" value="dark" />
                                <Select.Option label="Light" value="light" />
                            </Select>
                        </ControlGroup>
                        <ControlGroup label="Preview data">
                            <Select value={config.data_strategy} onChange={setField('data_strategy')}>
                                <Select.Option label="Run the search" value="search" />
                                <Select.Option label="Sample data" value="sample" />
                            </Select>
                        </ControlGroup>
                        <ControlGroup label="Post-search (optional)"
                            help="Piped onto the alert results, e.g. | timechart count by status.">
                            <Text multiline rowsMax={6} placeholder="| timechart count by status"
                                value={config.post_search || ''} onChange={setField('post_search')} />
                        </ControlGroup>
                        <ControlGroup label="Viz options (JSON)">
                            <Text multiline rowsMax={8} value={optionsText}
                                onChange={(e, { value }) => setOptionsText(value)} />
                        </ControlGroup>
                        <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
                            <Button appearance="primary" onClick={onPreview} disabled={!selected || previewing}
                                label={previewing ? 'Rendering…' : 'Preview'} />
                            <Button onClick={onSave} disabled={!selected || saving}
                                label={saving ? 'Saving…' : 'Save'} />
                        </div>
                        <div style={{ marginTop: 8 }}>
                            <Switch value="attach" selected={attachAction} appearance="checkbox"
                                onClick={() => setAttachAction((v) => !v)}>
                                Attach the “Render Viz &amp; Notify” action to this alert on save
                            </Switch>
                        </div>
                    </Card>

                    <Card style={{ padding: 16, marginTop: 16, width: '100%', boxSizing: 'border-box' }}>
                        <Heading level={3}>Destinations</Heading>
                        {(config.destinations || []).length === 0 && (
                            <P style={{ opacity: 0.7 }}>No destinations yet — add one below.</P>
                        )}
                        {(config.destinations || []).map((d, idx) => {
                            const ch = channels.find((c) => c.type === d.type);
                            const needsCred = (ch?.cred_keys || []).some((k) => !credsSet[k]);
                            return (
                                <div key={idx} style={{ border: '1px solid #3c444d', borderRadius: 4, padding: 12, marginBottom: 10 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                                        <span style={{ fontWeight: 'bold' }}>{ch?.label || d.type}</span>
                                        <div style={{ display: 'flex', gap: 6 }}>
                                            <Button size="small" label={testing === idx ? 'Sending…' : 'Test'}
                                                disabled={testing !== null} onClick={() => onTest(idx)} />
                                            <Button appearance="destructive" size="small" label="Remove" onClick={() => removeDest(idx)} />
                                        </div>
                                    </div>
                                    {(ch?.fields || []).map((f) => (
                                        <ControlGroup key={f.name} label={f.label} labelWidth={130}>
                                            {f.options ? (
                                                <Select value={d[f.name] || f.options[0]}
                                                    onChange={(e, { value }) => setDest(idx, f.name, value)}>
                                                    {f.options.map((o) => <Select.Option key={o} label={o} value={o} />)}
                                                </Select>
                                            ) : (
                                                <Text value={d[f.name] || ''} onChange={(e, { value }) => setDest(idx, f.name, value)} />
                                            )}
                                        </ControlGroup>
                                    ))}
                                    {needsCred && (
                                        <span style={{ color: '#f5c869', fontSize: 12 }}>
                                            Needs a credential — set it in “Channels…”.
                                        </span>
                                    )}
                                </div>
                            );
                        })}
                        <ControlGroup label="Add destination">
                            <Select value="" onChange={(e, { value }) => value && addDest(value)}>
                                <Select.Option label="Add a destination…" value="" />
                                {channels.map((c) => <Select.Option key={c.type} label={c.label} value={c.type} />)}
                            </Select>
                        </ControlGroup>
                    </Card>
                </div>

                {/* Preview fills the remaining width */}
                <div style={{ flex: '1 1 480px', minWidth: 0 }}>
                    <Card style={{ padding: 16, minHeight: 320 }}>
                        <Heading level={3}>Preview</Heading>
                        {previewing && <WaitSpinner size="medium" />}
                        {!previewing && preview && (
                            <>
                                <ResultsTable title="Raw results" data={preview.raw} />
                                {preview.post_applied && <ResultsTable title="Post-processed results" data={preview.processed} />}
                                {preview.png_b64 && (
                                    <div style={{ marginTop: 16 }}>
                                        <Heading level={4}>Visualization</Heading>
                                        <img alt="visualization preview" src={`data:image/png;base64,${preview.png_b64}`}
                                            style={{ maxWidth: '100%', border: '1px solid #3c444d', borderRadius: 4 }} />
                                        <P style={{ opacity: 0.7 }}>
                                            {preview.processed?.total} rows · {preview.viz_type}
                                            {preview.post_applied ? ' · post-search applied' : ''}
                                        </P>
                                    </div>
                                )}
                            </>
                        )}
                        {!previewing && !preview && (
                            <P>Choose a search and click <strong>Preview</strong> to see the data flow and image.</P>
                        )}
                    </Card>
                </div>
            </div>

            <Modal onRequestClose={() => setSettingsOpen(false)} open={settingsOpen} returnFocus={channelsBtn}>
                <Modal.Header title="Channel credentials" onRequestClose={() => setSettingsOpen(false)} />
                <Modal.Body>
                    <P>Stored encrypted in Splunk (storage/passwords). Leave blank to keep a saved value; clear to remove.</P>
                    {credKeys.map((k) => (
                        <ControlGroup key={k} label={CRED_LABELS[k] || k} help={credsSet[k] ? 'configured' : 'not set'}>
                            <Text type="password" value={tokenInputs[k] || ''}
                                placeholder={credsSet[k] ? '••••••••  (saved)' : ''}
                                onChange={(e, { value }) => setTokenInputs((t) => ({ ...t, [k]: value }))} />
                        </ControlGroup>
                    ))}
                </Modal.Body>
                <Modal.Footer>
                    <Button appearance="secondary" onClick={() => setSettingsOpen(false)} label="Cancel" />
                    <Button appearance="primary" onClick={onSaveTokens} label="Save" />
                </Modal.Footer>
            </Modal>
        </div>
    );
}
