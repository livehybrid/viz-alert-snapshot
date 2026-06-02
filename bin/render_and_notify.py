#!/usr/bin/env python
"""
render_and_notify.py — custom alert action: render the alert's results as a
single Splunk visualization (PNG) ONCE, then deliver it to every configured
destination (email / Telegram / Slack / webhook).

Config resolution at fire time:
  1. The saved Visual Alerts config in the KV store (keyed by the search name) —
     this is what the config UI writes: viz settings, post-search, destinations.
  2. Falls back to the alert-action params (so it also works without the UI:
     a single email destination from param.to).

Channel credentials (bot tokens) come from storage/passwords, never the payload.
"""
import os
import sys
import csv
import gzip
import json
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import snapshot           # noqa: E402
import kvstore            # noqa: E402
import secrets as channel_secrets  # noqa: E402
import senders            # noqa: E402

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format='%(asctime)s render_and_notify %(levelname)s %(message)s')
log = logging.getLogger('render_and_notify')


def read_results(path):
    if not path or not os.path.exists(path):
        return []
    with gzip.open(path, 'rt', newline='') as f:
        return list(csv.DictReader(f))


def loadjob_post(session_key, sid, post_search):
    post = (post_search or '').strip()
    if not post.startswith('|'):
        post = '| ' + post
    spl = '| loadjob %s %s' % (json.dumps(sid), post)
    try:
        import splunk.rest as rest
        _, content = rest.simpleRequest(
            '/servicesNS/nobody/viz-alert-snapshot/search/jobs',
            sessionKey=session_key,
            postargs={'search': spl, 'exec_mode': 'oneshot', 'output_mode': 'json',
                      'count': 50000}, method='POST')
        return json.loads(content).get('results', [])
    except Exception as e:
        log.warning('loadjob post-search failed (%s); using raw results', e)
        return None


def load_config(session_key, search_name, params):
    """Merge KV config (preferred) over alert-action params."""
    doc = {}
    try:
        doc = kvstore.get(session_key, search_name) or {}
    except Exception as e:
        log.info('no KV config for "%s" (%s); using params', search_name, e)

    def opt(key, default=None):
        if doc.get(key) not in (None, '', []):
            return doc.get(key)
        return params.get(key, default)

    options = opt('options', {})
    if isinstance(options, str):
        try:
            options = json.loads(options or '{}')
        except ValueError:
            options = {}

    destinations = doc.get('destinations') or []
    if not destinations and params.get('to'):
        destinations = [{'type': 'email', 'to': params['to']}]

    return {
        'viz_type': opt('viz_type', 'splunk.line'),
        'options': options,
        'width': int(opt('width', 800) or 800),
        'height': int(opt('height', 450) or 450),
        'theme': opt('theme', 'dark'),
        'post_search': opt('post_search', ''),
        'destinations': destinations,
    }


def main():
    if len(sys.argv) < 2 or sys.argv[1] != '--execute':
        sys.stderr.write('Usage: render_and_notify.py --execute  (called by Splunk)\n')
        return 2

    payload = json.load(sys.stdin)
    params = payload.get('configuration', {}) or {}
    search_name = payload.get('search_name', 'Splunk Alert')
    session_key = payload.get('session_key')
    server_uri = payload.get('server_uri')
    sid = payload.get('sid')

    subject = params.get('subject') or ('Splunk Alert: %s' % search_name)
    body = params.get('message') or ('The alert "%s" fired.' % search_name)

    if not snapshot.exporter_available():
        log.error('splunk-visual-exporter not installed — cannot render. Aborting.')
        return 2

    cfg = load_config(session_key, search_name, params)
    if not cfg['destinations']:
        log.error('No destinations configured for "%s". Aborting.', search_name)
        return 2

    rows = read_results(payload.get('results_file'))
    if cfg['post_search'] and sid and session_key:
        processed = loadjob_post(session_key, sid, cfg['post_search'])
        if processed is not None:
            rows = processed
    if not rows:
        log.warning('No results to render; sending nothing.')
        return 0

    try:
        png, definition, errors = snapshot.render_results_to_png(
            cfg['viz_type'], rows, width=cfg['width'], height=cfg['height'],
            title=search_name, options=cfg['options'], theme=cfg['theme'],
            screenshot_delay=0)
    except Exception as e:
        log.exception('Render failed: %s', e)
        return 2
    log.info('Rendered PNG (%d bytes) for "%s"; %d destinations',
             len(png), search_name, len(cfg['destinations']))

    try:
        creds = channel_secrets.get_creds(session_key)
    except Exception as e:
        log.warning('could not read channel creds (%s)', e)
        creds = {}

    ctx = {'subject': subject, 'body': body, 'search_name': search_name,
           'viz_type': cfg['viz_type'], 'server_uri': server_uri,
           'session_key': session_key, 'creds': creds}

    results = senders.dispatch(cfg['destinations'], png, ctx)
    failures = 0
    for r in results:
        lvl = log.info if r['ok'] else log.error
        lvl('  -> %s [%s]: %s', r.get('type'), r.get('target'), r.get('detail'))
        failures += 0 if r['ok'] else 1
    log.info('Delivered to %d/%d destinations', len(results) - failures, len(results))
    return 0 if failures == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
