"""
testsend_api.py — persistent REST: render the current config now and deliver to
the given destination(s), so users can test without firing a real alert.

passSystemAuth=true: credentials are read with the **system** token (so testing
doesn't require the password-read capability), while the search/preview data is
fetched with the calling **user's** token (their own search access). Gated by the
`run_visual_alert` capability in restmap.conf.

POST body: a config doc (same shape as preview/save); `destinations` is the list
to send to (the UI sends one for a per-destination "Test").
"""
import os
import sys
import json
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
sys.path.insert(0, os.path.dirname(__file__))
import snapshot   # noqa: E402
import deliver    # noqa: E402
import preview    # noqa: E402  (reuse raw/processed data logic)

from splunk.persistconn.application import PersistentServerConnectionApplication  # noqa: E402

logging.basicConfig(
    filename=os.path.join(os.environ.get('SPLUNK_HOME', '/opt/splunk'),
                          'var', 'log', 'splunk', 'viz_alert_snapshot.log'),
    level=logging.INFO, format='%(asctime)s testsend %(levelname)s %(message)s')
log = logging.getLogger('viz_alert_testsend')


class TestSendHandler(PersistentServerConnectionApplication):
    def __init__(self, command_line=None, command_arg=None):
        super().__init__()

    def handle(self, in_string):
        try:
            req = json.loads(in_string)
            user_key = (req.get('session') or {}).get('authtoken')
            sys_key = req.get('system_authtoken') or user_key
            if not user_key:
                return {'status': 401, 'payload': json.dumps({'error': 'no session'})}
            cfg = json.loads(req.get('payload') or '{}')
            if not (cfg.get('destinations') or []):
                return {'status': 400, 'payload': json.dumps({'error': 'no destinations to test'})}
            if not snapshot.exporter_available():
                return {'status': 503, 'payload': json.dumps(
                    {'error': 'splunk-visual-exporter not installed'})}

            # data with the USER token (their search); creds with the SYSTEM token
            _, processed, _ = preview._raw_and_processed(user_key, cfg)
            name = cfg.get('search_name') or 'Visual Alerts'
            results, _errors = deliver.render_and_deliver(
                cfg, processed, sys_key, name,
                '[TEST] %s' % name, 'Test send from the Visual Alerts app.')
            return {'status': 200, 'payload': json.dumps({'results': results})}
        except Exception as e:
            log.exception('testsend failed')
            return {'status': 500, 'payload': json.dumps({'error': str(e)})}
