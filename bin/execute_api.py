"""
execute_api.py — persistent REST worker for visual alerts.

This is where the delivery actually happens. It runs with passSystemAuth=true,
so it can read channel credentials (storage/passwords) using the **system** auth
token — the user firing the alert only needs the `run_visual_alert` capability
(enforced in restmap.conf via capability.post), NOT the ability to read passwords.

The alert action (render_and_notify.py) forwards the alert payload here.

POST body (JSON, forwarded by the alert action):
  { "search_name": "...", "sid": "...", "results_file": "/path.csv.gz",
    "configuration": { ...alert action params... } }
"""
import os
import sys
import json
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import snapshot   # noqa: E402
import deliver    # noqa: E402

from splunk.persistconn.application import PersistentServerConnectionApplication  # noqa: E402

logging.basicConfig(
    filename=os.path.join(os.environ.get('SPLUNK_HOME', '/opt/splunk'),
                          'var', 'log', 'splunk', 'viz_alert_snapshot.log'),
    level=logging.INFO, format='%(asctime)s execute %(levelname)s %(message)s')
log = logging.getLogger('viz_alert_execute')


class ExecuteHandler(PersistentServerConnectionApplication):
    def __init__(self, command_line=None, command_arg=None):
        super().__init__()

    def handle(self, in_string):
        try:
            req = json.loads(in_string)
            # system token (passSystemAuth) for creds/KV/loadjob; user token authenticated the call
            sys_key = req.get('system_authtoken') or (req.get('session') or {}).get('authtoken')
            if not sys_key:
                return {'status': 401, 'payload': json.dumps({'error': 'no auth'})}
            body = json.loads(req.get('payload') or '{}')

            if not snapshot.exporter_available():
                return {'status': 503, 'payload': json.dumps(
                    {'error': 'splunk-visual-exporter not installed'})}

            search_name = body.get('search_name', 'Splunk Alert')
            params = body.get('configuration') or {}
            cfg = deliver.load_config(sys_key, search_name, params)
            if not cfg['destinations']:
                return {'status': 200, 'payload': json.dumps(
                    {'delivered': 0, 'note': 'no destinations configured'})}

            rows = deliver.read_results(body.get('results_file'))
            if cfg['post_search'] and body.get('sid'):
                processed = deliver.loadjob_post(sys_key, body['sid'], cfg['post_search'])
                if processed is not None:
                    rows = processed
            if not rows:
                return {'status': 200, 'payload': json.dumps({'delivered': 0, 'note': 'no results'})}

            subject = params.get('subject') or ('Splunk Alert: %s' % search_name)
            message = params.get('message') or ('The alert "%s" fired.' % search_name)
            results, errors = deliver.render_and_deliver(cfg, rows, sys_key, search_name, subject, message)

            failed = [r for r in results if not r['ok']]
            for r in results:
                (log.info if r['ok'] else log.error)('  -> %s [%s]: %s',
                                                     r.get('type'), r.get('target'), r.get('detail'))
            return {'status': 200, 'payload': json.dumps(
                {'delivered': len(results) - len(failed), 'total': len(results), 'results': results})}
        except Exception as e:
            log.exception('execute failed')
            return {'status': 500, 'payload': json.dumps({'error': str(e)})}
