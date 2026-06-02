"""
snapshot.py — shared helpers for the viz-alert-snapshot app.

Turns Splunk search results into a one-panel Dashboard Studio definition
(ds.test) and renders it to a PNG using Splunk's *bundled* headless Chromium
(the splunk-visual-exporter app's ChromiumEngine). No external browser.
"""
import os
import re
import sys
import json
import base64
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Locate the bundled exporter (splunk-visual-exporter) and import its engine.
# ---------------------------------------------------------------------------

def _exporter_bin_path():
    try:
        from splunk.clilib.bundle_paths import make_splunkhome_path
        return make_splunkhome_path(['etc', 'apps', 'splunk-visual-exporter', 'bin'])
    except Exception:
        sh = os.environ.get('SPLUNK_HOME', '/opt/splunk')
        return os.path.join(sh, 'etc', 'apps', 'splunk-visual-exporter', 'bin')


def exporter_available():
    return os.path.isdir(_exporter_bin_path())


def _load_engine():
    """Import ChromiumEngine from the bundled exporter app. Raises if absent."""
    p = _exporter_bin_path()
    if not os.path.isdir(p):
        raise RuntimeError(
            "splunk-visual-exporter app not found at %s — this app reuses Splunk's "
            "bundled Chromium and requires Dashboard Studio export to be present." % p)
    if p not in sys.path:
        sys.path.append(p)
    from export_utils.chromium.engine import ChromiumEngine  # noqa: E402
    return ChromiumEngine


# ---------------------------------------------------------------------------
# Results -> ds.test
# ---------------------------------------------------------------------------

_EPOCH_RE = re.compile(r'^\d{9,10}(\.\d+)?$')


def _coerce_column(name, values):
    """Decide a column's emitted values. Numbers stay numbers; _time becomes ISO."""
    vals = list(values)
    if name == '_time':
        out = []
        for v in vals:
            s = str(v).strip()
            if _EPOCH_RE.match(s):
                out.append(datetime.fromtimestamp(float(s), tz=timezone.utc)
                           .strftime('%Y-%m-%dT%H:%M:%S.000Z'))
            else:
                out.append(s)  # already a formatted/ISO time string
        return out, True  # is_timestamp
    # numeric column? only if every non-empty value parses as a float
    nonempty = [v for v in vals if str(v).strip() != '']
    if nonempty and all(_is_number(v) for v in nonempty):
        return [None if str(v).strip() == '' else float(v) for v in vals], False
    return [str(v) for v in vals], False


def _is_number(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def results_to_dstest(rows, field_order=None, max_rows=2000):
    """
    rows: list of dicts (Splunk results). Returns a ds.test `data` object:
        { "fields": [{"name":..,"type":..?}], "columns": [[...], ...] }
    Field order follows `field_order` (e.g. the search's field list) when given,
    else the keys of the first row (Splunk-internal `_*` fields except `_time`
    are dropped).
    """
    rows = list(rows)[:max_rows]
    if not rows:
        return {"fields": [{"name": "value"}], "columns": [[]]}

    if field_order:
        names = [f for f in field_order if any(f in r for r in rows)]
    else:
        names = [k for k in rows[0].keys() if k == '_time' or not k.startswith('_')]
    if not names:
        names = list(rows[0].keys())

    fields, columns = [], []
    for name in names:
        raw = [r.get(name, '') for r in rows]
        col, is_ts = _coerce_column(name, raw)
        fields.append({"name": name, "type": "timestamp"} if is_ts else {"name": name})
        columns.append(col)
    return {"fields": fields, "columns": columns}


# ---------------------------------------------------------------------------
# Definition builder
# ---------------------------------------------------------------------------

def build_definition(viz_type, ds_data, width=800, height=450, title=None,
                     options=None, theme='dark'):
    """Wrap a single viz + ds.test source in a minimal one-panel Studio definition."""
    options = options or {}
    w, h = int(width), int(height)
    viz = {"type": viz_type, "dataSources": {"primary": "ds_snapshot"}}
    if title:
        viz["title"] = title
    if options:
        viz["options"] = options
    return {
        "title": title or "Snapshot",
        "visualizations": {"viz_snapshot": viz},
        "dataSources": {
            "ds_snapshot": {"type": "ds.test", "name": "Snapshot data",
                            "options": {"data": ds_data}}
        },
        "inputs": {},
        "layout": {
            "type": "absolute",
            "options": {"width": w, "height": h, "display": "auto"},
            "structure": [{"item": "viz_snapshot", "type": "block",
                           "position": {"x": 0, "y": 0, "w": w, "h": h}}],
        },
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_png_bytes(definition, theme='dark', screenshot_delay=0, timeout=30):
    """Render a Studio definition to PNG bytes via the bundled Chromium engine."""
    ChromiumEngine = _load_engine()
    engine = ChromiumEngine()
    errors = []
    data_uri = engine.get_screenshot(
        definition, theme, {}, errors,
        timeout=timeout, screenshot_delay=screenshot_delay, file_format='png')
    if not data_uri:
        raise RuntimeError("Chromium render returned no image. Engine errors: %s" % errors)
    b64 = data_uri.split(',', 1)[1]
    return base64.b64decode(b64), errors


def render_results_to_png(viz_type, rows, field_order=None, width=800, height=450,
                          title=None, options=None, theme='dark', screenshot_delay=0):
    """End-to-end: results rows -> single-viz PNG bytes."""
    ds_data = results_to_dstest(rows, field_order=field_order)
    definition = build_definition(viz_type, ds_data, width, height, title, options, theme)
    png, errors = render_png_bytes(definition, theme=theme, screenshot_delay=screenshot_delay)
    return png, definition, errors
