#!/usr/bin/env python
"""
render_and_notify.py — custom alert action (thin shim).

It does NOT render or read credentials itself. Instead it forwards the alert
payload to the `viz_alert/execute` REST endpoint using the firing user's session.
That endpoint runs with passSystemAuth=true and is gated by the
`run_visual_alert` capability — so the heavy work (and reading channel
credentials from storage/passwords) happens under system auth, and the firing
user only needs `run_visual_alert`, not the ability to read passwords.

Splunk invokes this as: render_and_notify.py --execute  (JSON payload on stdin).
"""
import os
import sys
import ssl
import json
import http.client
import logging

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format='%(asctime)s render_and_notify %(levelname)s %(message)s')
log = logging.getLogger('render_and_notify')

EXECUTE_PATH = '/servicesNS/nobody/viz-alert-snapshot/viz_alert/execute'


def _post_execute(session_key, body, host='127.0.0.1', port=8089):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    payload = json.dumps(body).encode('utf-8')
    conn = http.client.HTTPSConnection(host, port, context=ctx, timeout=120)
    try:
        conn.request('POST', EXECUTE_PATH, body=payload, headers={
            'Authorization': 'Splunk ' + session_key,
            'Content-Type': 'application/json',
            'Content-Length': str(len(payload)),
        })
        resp = conn.getresponse()
        return resp.status, resp.read().decode('utf-8', 'replace')
    finally:
        conn.close()


def main():
    if len(sys.argv) < 2 or sys.argv[1] != '--execute':
        sys.stderr.write('Usage: render_and_notify.py --execute  (called by Splunk)\n')
        return 2

    payload = json.load(sys.stdin)
    session_key = payload.get('session_key')
    if not session_key:
        log.error('No session_key in payload; cannot call execute endpoint.')
        return 2

    forward = {
        'search_name': payload.get('search_name', 'Splunk Alert'),
        'sid': payload.get('sid'),
        'results_file': payload.get('results_file'),
        'configuration': payload.get('configuration', {}) or {},
    }
    try:
        status, text = _post_execute(session_key, forward)
    except Exception as e:
        log.exception('Failed to call execute endpoint: %s', e)
        return 2

    if status == 403:
        log.error('Execute endpoint denied (403). The firing user/role needs the '
                  '"run_visual_alert" capability. Response: %s', text[:300])
        return 2
    if status >= 400:
        log.error('Execute endpoint error %s: %s', status, text[:500])
        return 2
    log.info('Execute result: %s', text[:500])
    return 0


if __name__ == '__main__':
    sys.exit(main())
