"""
preview.py — persistent REST handler: render a viz config to a PNG for the UI,
with an optional post-search (post-process) pipeline.

POST body (JSON):
  {
    "viz_type": "splunk.line", "options": {...},
    "width": 800, "height": 450, "theme": "dark", "title": "...",
    "data_strategy": "search" | "sample",
    "search_name": "...", "search_app": "...",   # when data_strategy=search
    "spl": "...",                                  # alt to search_name
    "post_search": "| timechart count by status", # optional post-process SPL
    "rows": [ {..}, .. ]                           # explicit data (overrides)
  }

Response (JSON):
  {
    "raw":       { "fields": [...], "rows": [ {..}, .. ], "total": N },
    "processed": { "fields": [...], "rows": [ {..}, .. ], "total": N },
    "post_applied": true|false,
    "png_b64": "...", "viz_type": "...", "notes": [...]
  }

The viz is rendered from the *processed* rows (post-search applied), so preview
matches fire-time, where the alert action runs `| loadjob <sid> | <post_search>`.
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

APP = 'viz-alert-snapshot'
MAX_PREVIEW_ROWS = 2000
TABLE_LIMIT = 100

SAMPLE_ROWS = [
    {'_time': '2026-06-01T%02d:00:00.000Z' % h, 'count': v}
    for h, v in enumerate([120, 138, 165, 150, 175, 210, 245, 230, 260, 248, 275, 290])
]


def _oneshot(session_key, spl, earliest='-24h', latest='now', count=MAX_PREVIEW_ROWS,
             search_app=None):
    """Run a count-limited oneshot search in the search's own app context."""
    import splunk.rest as rest
    if not spl.lstrip().startswith(('search ', '|', 'search\t')):
        spl = 'search ' + spl
    postargs = {
        'search': spl, 'exec_mode': 'oneshot', 'output_mode': 'json',
        'earliest_time': earliest, 'latest_time': latest, 'count': count,
    }
    _, content = rest.simpleRequest(
        '/servicesNS/nobody/%s/search/jobs' % (search_app or APP),
        sessionKey=session_key, postargs=postargs, method='POST')
    return json.loads(content).get('results', [])


def _resolve_spl(session_key, search_name, search_app=None):
    """Resolve a saved search name to its SPL + dispatch time range."""
    import splunk.rest as rest
    from urllib.parse import quote
    _, content = rest.simpleRequest(
        '/servicesNS/-/%s/saved/searches/%s' % (search_app or '-', quote(search_name, safe='')),
        sessionKey=session_key, getargs={'output_mode': 'json'})
    c = (json.loads(content).get('entry') or [{}])[0].get('content', {})
    return c.get('search', ''), c.get('dispatch.earliest_time', '-24h'), \
        c.get('dispatch.latest_time', 'now')


def _join_post(base_spl, post_search):
    """Append a post-search pipeline to a base search, fixing the leading pipe."""
    post = (post_search or '').strip()
    if not post:
        return base_spl
    if not post.startswith('|'):
        post = '| ' + post
    return '%s %s' % (base_spl, post)


def _table(rows):
    """Shape rows for a UI table: ordered field list + a capped row sample."""
    rows = list(rows)
    fields = []
    for r in rows[:TABLE_LIMIT]:
        for k in r.keys():
            if k not in fields:
                fields.append(k)
    return {'fields': fields, 'rows': rows[:TABLE_LIMIT], 'total': len(rows)}


def _raw_and_processed(session_key, cfg):
    """Return (raw_rows, processed_rows, post_applied)."""
    post = (cfg.get('post_search') or '').strip()

    # Explicit rows or sample data: can't run SPL, so post-search is a no-op.
    if cfg.get('rows'):
        rows = list(cfg['rows'])[:MAX_PREVIEW_ROWS]
        return rows, rows, False
    if cfg.get('data_strategy') == 'sample':
        return SAMPLE_ROWS, SAMPLE_ROWS, False

    spl = cfg.get('spl')
    earliest = cfg.get('earliest', '-24h')
    latest = cfg.get('latest', 'now')
    search_app = cfg.get('search_app')
    if not spl and cfg.get('search_name'):
        spl, earliest, latest = _resolve_spl(session_key, cfg['search_name'], search_app)
    if not spl:
        return SAMPLE_ROWS, SAMPLE_ROWS, False

    raw = _oneshot(session_key, spl, earliest, latest, search_app=search_app) or []
    if not post:
        return raw, raw, False
    try:
        processed = _oneshot(session_key, _join_post(spl, post), earliest, latest,
                             search_app=search_app) or []
        return raw, processed, True
    except Exception as e:
        log.warning('post-search failed (%s); showing base results', e)
        return raw, raw, False


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

            raw, processed, post_applied = _raw_and_processed(session_key, cfg)

            png, definition, errors = snapshot.render_results_to_png(
                cfg.get('viz_type', 'splunk.line'), processed,
                width=int(cfg.get('width') or 800),
                height=int(cfg.get('height') or 450),
                title=cfg.get('title'),
                options=cfg.get('options') or {},
                theme=cfg.get('theme') or 'dark',
                screenshot_delay=0)

            return {'status': 200, 'payload': json.dumps({
                'raw': _table(raw),
                'processed': _table(processed),
                'post_applied': post_applied,
                'png_b64': base64.b64encode(png).decode('ascii'),
                'viz_type': cfg.get('viz_type', 'splunk.line'),
                'notes': errors[:3] if errors else [],
            })}
        except Exception as e:
            log.exception('preview failed')
            return {'status': 500, 'payload': json.dumps({'error': str(e)})}
