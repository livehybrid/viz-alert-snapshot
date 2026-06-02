"""
deliver.py — shared "render once + fan out" core, plus config/results helpers.

Used by the execute endpoint (alert path) and the test-send endpoint. Credential
reading is done with whatever token the caller passes as `creds_key` — the
endpoints pass the **system** auth token (from passSystemAuth=true), so the user
firing the alert does NOT need the capability to read storage/passwords.
"""
import os
import csv
import gzip
import json

import snapshot
import secrets as channel_secrets
import senders

LOCAL_SPLUNKD = 'https://127.0.0.1:8089'
APP = 'viz-alert-snapshot'


def read_results(path):
    if not path or not os.path.exists(path):
        return []
    with gzip.open(path, 'rt', newline='') as f:
        return list(csv.DictReader(f))


def loadjob_post(auth_key, sid, post_search):
    """`| loadjob <sid> | <post_search>` — transform the alert's own results."""
    post = (post_search or '').strip()
    if not post.startswith('|'):
        post = '| ' + post
    spl = '| loadjob %s %s' % (json.dumps(sid), post)
    import splunk.rest as rest
    _, content = rest.simpleRequest(
        '/servicesNS/nobody/%s/search/jobs' % APP, sessionKey=auth_key,
        postargs={'search': spl, 'exec_mode': 'oneshot', 'output_mode': 'json', 'count': 50000},
        method='POST')
    return json.loads(content).get('results', [])


def load_config(auth_key, search_name, params):
    """Merge the saved KV config (preferred) over alert-action params."""
    import kvstore
    doc = {}
    try:
        doc = kvstore.get(auth_key, search_name) or {}
    except Exception:
        doc = {}

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


def render_and_deliver(cfg, rows, creds_key, search_name, subject, body,
                       server_uri=LOCAL_SPLUNKD):
    """Render the rows to a PNG and dispatch to all of cfg['destinations']."""
    png, _definition, errors = snapshot.render_results_to_png(
        cfg.get('viz_type', 'splunk.line'), rows,
        width=int(cfg.get('width') or 800), height=int(cfg.get('height') or 450),
        title=search_name, options=cfg.get('options') or {},
        theme=cfg.get('theme') or 'dark', screenshot_delay=0)
    try:
        creds = channel_secrets.get_creds(creds_key)
    except Exception:
        creds = {}
    ctx = {
        'subject': subject, 'body': body, 'search_name': search_name,
        'viz_type': cfg.get('viz_type', 'splunk.line'),
        'server_uri': server_uri, 'session_key': creds_key, 'creds': creds,
    }
    results = senders.dispatch(cfg.get('destinations') or [], png, ctx)
    return results, errors
