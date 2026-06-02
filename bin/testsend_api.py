"""
testsend_api.py — persistent REST: render the current config now and deliver it
to the given destination(s), so users can test without firing a real alert.

POST body: a config doc (same shape as preview/save) — `destinations` is the
list to send to (the UI sends just one for a per-destination "Test").
Response: { results: [ {type, target, ok, detail}, ... ] }
"""
import os
import sys
import json
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
sys.path.insert(0, os.path.dirname(__file__))
import snapshot                    # noqa: E402
import senders                     # noqa: E402
import secrets as channel_secrets  # noqa: E402
import preview                     # noqa: E402  (reuse raw/processed data logic)

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
            session_key = (req.get('session') or {}).get('authtoken')
            if not session_key:
                return {'status': 401, 'payload': json.dumps({'error': 'no session'})}
            cfg = json.loads(req.get('payload') or '{}')
            dests = cfg.get('destinations') or []
            if not dests:
                return {'status': 400, 'payload': json.dumps({'error': 'no destinations to test'})}
            if not snapshot.exporter_available():
                return {'status': 503, 'payload': json.dumps(
                    {'error': 'splunk-visual-exporter not installed — cannot render'})}

            _, processed, _ = preview._raw_and_processed(session_key, cfg)
            png, _definition, errors = snapshot.render_results_to_png(
                cfg.get('viz_type', 'splunk.line'), processed,
                width=int(cfg.get('width') or 800), height=int(cfg.get('height') or 450),
                title=cfg.get('search_name') or 'Visual Alerts test',
                options=cfg.get('options') or {}, theme=cfg.get('theme') or 'dark',
                screenshot_delay=0)

            creds = channel_secrets.get_creds(session_key)
            name = cfg.get('search_name') or 'Visual Alerts'
            ctx = {
                'subject': '[TEST] %s' % name,
                'body': 'Test send from the Visual Alerts app.',
                'search_name': name, 'viz_type': cfg.get('viz_type', 'splunk.line'),
                'server_uri': 'https://127.0.0.1:8089',
                'session_key': session_key, 'creds': creds,
            }
            results = senders.dispatch(dests, png, ctx)
            return {'status': 200, 'payload': json.dumps({'results': results})}
        except Exception as e:
            log.exception('testsend failed')
            return {'status': 500, 'payload': json.dumps({'error': str(e)})}
