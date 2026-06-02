"""
preview.py — persistent REST handler: render a viz config to a PNG for the UI.

POST body (JSON):
  {
    "viz_type":   "splunk.line",
    "options":    { ... },              # Studio viz options
    "width":      800, "height": 450,
    "theme":      "dark" | "light",
    "title":      "My panel",
    "data_strategy": "search" | "sample",
    "search_name": "<saved search name>",   # when data_strategy=search
    "spl":         "<raw SPL>",              # alt to search_name
    "earliest":    "-24h", "latest": "now",
    "rows":        [ {field: value, ...}, ... ]  # explicit data (overrides)
  }

Response (JSON): { "png_b64": "...", "rows": N, "viz_type": "..." } or { "error": "..." }

Reuses lib/snapshot.py so the preview is the *same render* that fires on the
alert — WYSIWYG fidelity.
"""
import os
import sys
import json
import base64
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import snapshot  # noqa: E402

from splunk.persistconn.application import PersistentServerConnectionApplication  # noqa: E402

logging.basicConfig(
    filename=os.path.join(os.environ.get('SPLUNK_HOME', '/opt/splunk'),
                          'var', 'log', 'splunk', 'viz_alert_snapshot.log'),
    level=logging.INFO,
    format='%(asctime)s preview %(levelname)s %(message)s')
log = logging.getLogger('viz_alert_preview')

MAX_PREVIEW_ROWS = 2000

SAMPLE_ROWS = [
    {'_time': '2026-06-01T%02d:00:00.000Z' % h, 'count': v}
    for h, v in enumerate([120, 138, 165, 150, 175, 210, 245, 230, 260, 248, 275, 290])
]


def _oneshot(session_key, spl, earliest='-24h', latest='now', count=MAX_PREVIEW_ROWS):
    """Run a count-limited oneshot search and return result rows as dicts."""
    import splunklib.client as client
    import splunklib.results as results_reader
    if not spl.strip().lstrip().startswith(('search ', '|', 'search\t')):
        spl = 'search ' + spl
    service = client.connect(token=session_key, host='127.0.0.1', port=8089, scheme='https')
    job = service.jobs.oneshot(spl, earliest_time=earliest, latest_time=latest,
                               count=count, output_mode='json')
    rows = []
    for item in results_reader.JSONResultsReader(job):
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _resolve_spl(session_key, search_name):
    """Resolve a saved search name to its SPL + time range."""
    import splunklib.client as client
    service = client.connect(token=session_key, host='127.0.0.1', port=8089, scheme='https',
                             app='viz-alert-snapshot')
    ss = service.saved_searches[search_name]
    content = ss.content
    return content.get('search', ''), content.get('dispatch.earliest_time', '-24h'), \
        content.get('dispatch.latest_time', 'now')


def _get_rows(session_key, cfg):
    if cfg.get('rows'):
        return list(cfg['rows'])[:MAX_PREVIEW_ROWS]
    if cfg.get('data_strategy') == 'sample':
        return SAMPLE_ROWS
    spl = cfg.get('spl')
    earliest = cfg.get('earliest', '-24h')
    latest = cfg.get('latest', 'now')
    if not spl and cfg.get('search_name'):
        spl, earliest, latest = _resolve_spl(session_key, cfg['search_name'])
    if not spl:
        return SAMPLE_ROWS
    try:
        rows = _oneshot(session_key, spl, earliest, latest)
        return rows or SAMPLE_ROWS
    except Exception as e:
        log.warning('oneshot failed (%s); falling back to sample', e)
        return SAMPLE_ROWS


class PreviewHandler(PersistentServerConnectionApplication):
    def __init__(self, command_line=None, command_arg=None):
        super().__init__()

    def handle(self, in_string):
        try:
            req = json.loads(in_string)
            session_key = (req.get('session') or {}).get('authtoken')
            if not session_key:
                return {'status': 401, 'payload': json.dumps({'error': 'no session'})}
            cfg = json.loads(req.get('payload') or '{}')

            if not snapshot.exporter_available():
                return {'status': 503, 'payload': json.dumps(
                    {'error': 'splunk-visual-exporter not installed — cannot render'})}

            rows = _get_rows(session_key, cfg)
            png, definition, errors = snapshot.render_results_to_png(
                cfg.get('viz_type', 'splunk.line'), rows,
                width=int(cfg.get('width') or 800),
                height=int(cfg.get('height') or 450),
                title=cfg.get('title'),
                options=cfg.get('options') or {},
                theme=cfg.get('theme') or 'dark',
                screenshot_delay=0)
            return {'status': 200, 'payload': json.dumps({
                'png_b64': base64.b64encode(png).decode('ascii'),
                'rows': len(rows),
                'viz_type': cfg.get('viz_type', 'splunk.line'),
                'notes': errors[:3] if errors else [],
            })}
        except Exception as e:
            log.exception('preview failed')
            return {'status': 500, 'payload': json.dumps({'error': str(e)})}
