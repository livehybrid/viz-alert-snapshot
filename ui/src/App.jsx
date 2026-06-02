/*
 * App.jsx — Visual Alerts configuration UI.
 *
 * Point a saved search at a native Splunk visualization, preview the EXACT
 * image that will be sent (server-rendered, same engine as the alert), and save
 * the config. Splunk React UI components only.
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
import ColumnLayout from '@splunk/react-ui/ColumnLayout';
import Table from '@splunk/react-ui/Table';

import { getSavedSearches, getConfig, saveConfig, previewConfig } from './api';

/* A capped, scrollable results table (raw or post-processed). */
function ResultsTable({ title, data }) {
    if (!data || !(data.rows || []).length) return null;
    return (
        <div style={{ marginTop: 16 }}>
            <Heading level={4}>
                {title} <Text as="span" style={{ opacity: 0.6 }}>({data.total} rows)</Text>
            </Heading>
            <div style={{ maxHeight: 200, overflow: 'auto', border: '1px solid #3c444d', borderRadius: 4 }}>
                <Table stripeRows>
                    <Table.Head>
                        {data.fields.map((f) => (
                            <Table.HeadCell key={f}>{f}</Table.HeadCell>
                        ))}
                    </Table.Head>
                    <Table.Body>
                        {data.rows.map((r, i) => (
                            <Table.Row key={i}>
                                {data.fields.map((f) => (
                                    <Table.Cell key={f}>{String(r[f] ?? '')}</Table.Cell>
                                ))}
                            </Table.Row>
                        ))}
                    </Table.Body>
                </Table>
            </div>
        </div>
    );
}

const VIZ_TYPES = [
    ['splunk.line', 'Line'],
    ['splunk.area', 'Area'],
    ['splunk.column', 'Column'],
    ['splunk.bar', 'Bar'],
    ['splunk.pie', 'Pie'],
    ['splunk.singlevalue', 'Single Value'],
    ['splunk.table', 'Table'],
    ['splunk.markdown', 'Markdown'],
];

const DEFAULT_CONFIG = {
    viz_type: 'splunk.line',
    width: 800,
    height: 450,
    theme: 'dark',
    data_strategy: 'search',
    post_search: '',
    options: {},
    destinations: [],
};

export default function App() {
    const [searches, setSearches] = useState([]);
    const [selected, setSelected] = useState('');
    const [config, setConfig] = useState(DEFAULT_CONFIG);
    const [optionsText, setOptionsText] = useState('{}');
    const [preview, setPreview] = useState(null); // { png_b64, rows }
    const [loading, setLoading] = useState(false);
    const [previewing, setPreviewing] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const [notice, setNotice] = useState(null);
    const previewAbort = useRef(null);

    // Load saved searches once.
    useEffect(() => {
        const ctrl = new AbortController();
        getSavedSearches(ctrl.signal)
            .then(setSearches)
            .catch((e) => setError(`Could not load saved searches: ${e.message}`));
        return () => ctrl.abort();
    }, []);

    // When a search is selected, load its existing config (or defaults).
    const onSelectSearch = useCallback((e, { value }) => {
        setSelected(value);
        setPreview(null);
        setNotice(null);
        setError(null);
        if (!value) return;
        const meta = searches.find((s) => s.name === value);
        setLoading(true);
        getConfig(value)
            .then((doc) => {
                const merged = {
                    ...DEFAULT_CONFIG, ...doc,
                    search_name: value, _key: value,
                    search_app: meta?.app, search_owner: meta?.owner,
                };
                setConfig(merged);
                setOptionsText(JSON.stringify(merged.options || {}, null, 2));
            })
            .catch((e2) => setError(`Could not load config: ${e2.message}`))
            .finally(() => setLoading(false));
    }, [searches]);

    const setField = (k) => (e, { value }) => setConfig((c) => ({ ...c, [k]: value }));

    const parsedOptions = () => {
        try {
            return [JSON.parse(optionsText || '{}'), null];
        } catch (e) {
            return [null, `Options JSON invalid: ${e.message}`];
        }
    };

    const currentConfig = () => {
        const [opts, optErr] = parsedOptions();
        if (optErr) throw new Error(optErr);
        return {
            _key: selected,
            search_name: selected,
            search_app: config.search_app,
            search_owner: config.search_owner,
            post_search: config.post_search || '',
            viz_type: config.viz_type,
            width: Number.isFinite(+config.width) ? +config.width : 800,
            height: Number.isFinite(+config.height) ? +config.height : 450,
            theme: config.theme,
            data_strategy: config.data_strategy,
            options: opts,
            destinations: config.destinations || [],
        };
    };

    const onPreview = useCallback(() => {
        setError(null);
        setNotice(null);
        let cfg;
        try {
            cfg = currentConfig();
        } catch (e) {
            setError(e.message);
            return;
        }
        if (previewAbort.current) previewAbort.current.abort();
        previewAbort.current = new AbortController();
        setPreviewing(true);
        previewConfig(cfg, previewAbort.current.signal)
            .then((res) => setPreview(res))
            .catch((e) => setError(`Preview failed: ${e.message}`))
            .finally(() => setPreviewing(false));
    }, [config, optionsText, selected]);

    const onSave = useCallback(() => {
        setError(null);
        let cfg;
        try {
            cfg = currentConfig();
        } catch (e) {
            setError(e.message);
            return;
        }
        setSaving(true);
        saveConfig(cfg)
            .then(() => setNotice(`Saved configuration for “${selected}”.`))
            .catch((e) => setError(`Save failed: ${e.message}`))
            .finally(() => setSaving(false));
    }, [config, optionsText, selected]);

    return (
        <div style={{ padding: 20, maxWidth: 1100, margin: '0 auto' }}>
            <Heading level={1}>Visual Alerts</Heading>
            <P>
                Point a saved search at a Splunk visualization, preview the exact image that will be
                sent when the alert fires, then save. Native Splunk visualizations, rendered
                server-side.
            </P>

            {error && (
                <Message appearance="fill" type="error" onRequestRemove={() => setError(null)}>
                    {error}
                </Message>
            )}
            {notice && (
                <Message appearance="fill" type="success" onRequestRemove={() => setNotice(null)}>
                    {notice}
                </Message>
            )}

            <ColumnLayout gutter={20}>
                <ColumnLayout.Row>
                    <ColumnLayout.Column span={5}>
                        <Card style={{ padding: 16 }}>
                            <Heading level={3}>Source &amp; visualization</Heading>
                            <ControlGroup label="Saved search">
                                <Select value={selected} onChange={onSelectSearch} filter>
                                    <Select.Option label="Select a saved search…" value="" />
                                    {[...searches]
                                        .sort((a, b) => a.name.localeCompare(b.name))
                                        .map((s) => (
                                            <Select.Option
                                                key={`${s.app}/${s.owner}/${s.name}`}
                                                label={`${s.name}  ·  ${s.app}`}
                                                value={s.name}
                                            />
                                        ))}
                                </Select>
                            </ControlGroup>

                            {loading && <WaitSpinner size="medium" />}

                            <ControlGroup label="Visualization">
                                <Select value={config.viz_type} onChange={setField('viz_type')}>
                                    {VIZ_TYPES.map(([v, l]) => (
                                        <Select.Option key={v} label={l} value={v} />
                                    ))}
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

                            <ControlGroup
                                label="Post-search (optional)"
                                help="Piped onto the alert results, e.g. | timechart count by status. Runs via loadjob on the alert's own results when it fires."
                            >
                                <Text
                                    multiline
                                    rowsMax={6}
                                    placeholder="| timechart count by status"
                                    value={config.post_search || ''}
                                    onChange={setField('post_search')}
                                />
                            </ControlGroup>

                            <ControlGroup label="Viz options (JSON)" help="Dashboard Studio viz options">
                                <Text
                                    multiline
                                    rowsMax={10}
                                    value={optionsText}
                                    onChange={(e, { value }) => setOptionsText(value)}
                                />
                            </ControlGroup>

                            <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
                                <Button
                                    appearance="primary"
                                    onClick={onPreview}
                                    disabled={!selected || previewing}
                                    label={previewing ? 'Rendering…' : 'Preview'}
                                />
                                <Button
                                    onClick={onSave}
                                    disabled={!selected || saving}
                                    label={saving ? 'Saving…' : 'Save'}
                                />
                            </div>
                        </Card>
                    </ColumnLayout.Column>

                    <ColumnLayout.Column span={7}>
                        <Card style={{ padding: 16, minHeight: 320 }}>
                            <Heading level={3}>Preview</Heading>
                            {previewing && <WaitSpinner size="medium" />}
                            {!previewing && preview && (
                                <>
                                    {/* Stage 1: raw alert results */}
                                    <ResultsTable title="Raw results" data={preview.raw} />

                                    {/* Stage 2: post-processed results (only when a post-search ran) */}
                                    {preview.post_applied && (
                                        <ResultsTable title="Post-processed results" data={preview.processed} />
                                    )}

                                    {/* Stage 3: the visualization */}
                                    {preview.png_b64 && (
                                        <div style={{ marginTop: 16 }}>
                                            <Heading level={4}>Visualization</Heading>
                                            <img
                                                alt="visualization preview"
                                                src={`data:image/png;base64,${preview.png_b64}`}
                                                style={{ maxWidth: '100%', border: '1px solid #3c444d', borderRadius: 4 }}
                                            />
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
                    </ColumnLayout.Column>
                </ColumnLayout.Row>
            </ColumnLayout>
        </div>
    );
}
