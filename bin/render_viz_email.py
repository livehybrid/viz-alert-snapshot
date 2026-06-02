#!/usr/bin/env python
"""
render_viz_email.py — custom alert action.

On alert fire: take the search results, render them as a single Dashboard Studio
visualization (PNG, via Splunk's bundled Chromium in the splunk-visual-exporter
app), and email the image using Splunk's configured email settings.

Splunk invokes this as:  render_viz_email.py --execute
with a JSON payload on stdin (payload_format = json).
"""
import os
import sys
import csv
import gzip
import json
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import snapshot          # noqa: E402
import mailer            # noqa: E402

logging.basicConfig(
    level=logging.INFO, stream=sys.stderr,
    format='%(asctime)s render_viz_email %(levelname)s %(message)s')
log = logging.getLogger('render_viz_email')


def read_results(path):
    if not path or not os.path.exists(path):
        return []
    with gzip.open(path, 'rt', newline='') as f:
        return list(csv.DictReader(f))


def loadjob_post(session_key, sid, post_search):
    """Run `| loadjob <sid> | <post_search>` against the alert's own job results.

    This reuses the search the alert already ran (no re-dispatch) and applies the
    post-process pipeline — e.g. turning a list of error events into a timechart.
    Returns a list of result dicts, or None on failure.
    """
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
                      'count': 50000},
            method='POST')
        return json.loads(content).get('results', [])
    except Exception as e:
        log.warning('loadjob post-search failed (%s); using raw results', e)
        return None


def main():
    if len(sys.argv) < 2 or sys.argv[1] != '--execute':
        sys.stderr.write('Usage: render_viz_email.py --execute  (called by Splunk)\n')
        return 2

    payload = json.load(sys.stdin)
    cfg = payload.get('configuration', {}) or {}
    search_name = payload.get('search_name', 'Splunk Alert')

    viz_type = cfg.get('viz_type', 'splunk.line').strip()
    to = [a.strip() for a in (cfg.get('to', '') or '').replace(';', ',').split(',') if a.strip()]
    subject = cfg.get('subject') or ('Splunk Alert: %s' % search_name)
    body = cfg.get('message') or ('The alert "%s" fired. Rendered visualization attached.' % search_name)
    width = int(cfg.get('width') or 800)
    height = int(cfg.get('height') or 450)
    theme = cfg.get('theme') or 'dark'
    delay = int(cfg.get("screenshot_delay") or 0)
    try:
        options = json.loads(cfg.get('options') or '{}')
    except (ValueError, TypeError):
        options = {}

    if not to:
        log.error('No recipients configured (param.to is empty). Aborting.')
        return 2
    if not snapshot.exporter_available():
        log.error('splunk-visual-exporter not installed — cannot render. Aborting.')
        return 2

    rows = read_results(payload.get('results_file'))

    # Optional post-search: transform the alert's own results before rendering
    # (e.g. raw error events -> timechart count). Runs via loadjob on the sid.
    post_search = (cfg.get('post_search') or '').strip()
    sid = payload.get('sid')
    session_key = payload.get('session_key')
    if post_search and sid and session_key:
        processed = loadjob_post(session_key, sid, post_search)
        if processed is not None:
            log.info('Post-search applied: %d raw -> %d processed rows', len(rows), len(processed))
            rows = processed

    log.info('Rendering %s for "%s": %d rows -> %dx%d',
             viz_type, search_name, len(rows), width, height)
    if not rows:
        log.warning('No results to render; sending nothing.')
        return 0

    try:
        png, definition, errors = snapshot.render_results_to_png(
            viz_type, rows, width=width, height=height, title=search_name,
            options=options, theme=theme, screenshot_delay=delay)
    except Exception as e:
        log.exception('Render failed: %s', e)
        return 2
    if errors:
        log.info('Engine notes: %s', errors[:3])
    log.info('Rendered PNG (%d bytes).', len(png))

    try:
        settings = mailer.get_email_settings(payload['server_uri'], payload['session_key'])
        encrypted = mailer.send_snapshot(settings, to, subject, body, png)
        if encrypted:
            log.warning('Splunk email auth_password is encrypted and was not usable; '
                        'sent without auth. Use an unauthenticated relay or set creds reachable to this action.')
        log.info('Emailed snapshot to %s via %s', to, settings['mailserver'])
    except Exception as e:
        log.exception('Email send failed: %s', e)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
