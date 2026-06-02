#!/usr/bin/env python
"""
render_and_notify.py — custom alert action (thin shim).

It does NOT render or read credentials itself. Instead it forwards the alert
payload to the `viz_alert/execute` REST endpoint using the firing user's session.
That endpoint runs with passSystemAuth=true and is gated by the
`run_visual_alert` capability — so the heavy work (and reading channel
credentials from storage/passwords) happens under system auth, and the firing
user only needs `run_visual_alert`, not the ability to read passwords.

The call uses splunk.rest.simpleRequest (TLS verified against Splunk's own CA).

Splunk invokes this as: render_and_notify.py --execute  (JSON payload on stdin).
"""
import sys
import json
import logging

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format='%(asctime)s render_and_notify %(levelname)s %(message)s')
log = logging.getLogger('render_and_notify')

EXECUTE_PATH = '/servicesNS/nobody/viz-alert-snapshot/viz_alert/execute'


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
        import splunk.rest as rest
        resp, content = rest.simpleRequest(
            EXECUTE_PATH, sessionKey=session_key,
            jsonargs=json.dumps(forward), method='POST', raiseAllErrors=False)
        status = int(resp.get('status', 0))
    except Exception as e:
        log.exception('Failed to call execute endpoint: %s', e)
        return 2

    if status == 403:
        log.error('Execute endpoint denied (403). The firing user/role needs the '
                  '"run_visual_alert" capability. Response: %s', content[:300])
        return 2
    if status >= 400:
        log.error('Execute endpoint error %s: %s', status, content[:500])
        return 2
    log.info('Execute result: %s', content[:500])
    return 0


if __name__ == '__main__':
    sys.exit(main())
