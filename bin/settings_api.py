"""
settings_api.py — persistent REST: channel registry + credential management.

  GET  /viz_alert/settings  -> { channels: [...], creds_set: { name: bool } }
  POST /viz_alert/settings  -> body { telegram_bot_token, slack_bot_token, ... }
                               sets non-empty values (encrypted); "" deletes.

Credential VALUES are never returned to the UI — only whether each is set.
"""
import os
import sys
import json
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import secrets as channel_secrets  # noqa: E402
import senders  # noqa: E402

from splunk.persistconn.application import PersistentServerConnectionApplication  # noqa: E402

logging.basicConfig(
    filename=os.path.join(os.environ.get('SPLUNK_HOME', '/opt/splunk'),
                          'var', 'log', 'splunk', 'viz_alert_snapshot.log'),
    level=logging.INFO, format='%(asctime)s settings_api %(levelname)s %(message)s')
log = logging.getLogger('viz_alert_settings')


class SettingsHandler(PersistentServerConnectionApplication):
    def __init__(self, command_line=None, command_arg=None):
        super().__init__()

    def handle(self, in_string):
        try:
            req = json.loads(in_string)
            session_key = (req.get('session') or {}).get('authtoken')
            if not session_key:
                return {'status': 401, 'payload': json.dumps({'error': 'no session'})}
            method = (req.get('method') or 'GET').upper()
            keys = senders.all_cred_keys()

            if method == 'GET':
                have = channel_secrets.get_creds(session_key)
                return {'status': 200, 'payload': json.dumps({
                    'channels': senders.registry(),
                    'creds_set': {k: bool(have.get(k)) for k in keys},
                })}

            if method == 'POST':
                body = json.loads(req.get('payload') or '{}')
                changed = []
                for k in keys:
                    if k not in body:
                        continue
                    v = (body.get(k) or '').strip()
                    if v:
                        channel_secrets.set_cred(session_key, k, v)
                        changed.append(k)
                    else:
                        try:
                            channel_secrets.delete_cred(session_key, k)
                        except Exception:
                            pass
                have = channel_secrets.get_creds(session_key)
                return {'status': 200, 'payload': json.dumps({
                    'ok': True, 'changed': changed,
                    'creds_set': {k: bool(have.get(k)) for k in keys},
                })}

            return {'status': 405, 'payload': json.dumps({'error': 'method not allowed'})}
        except Exception as e:
            log.exception('settings_api failed')
            return {'status': 500, 'payload': json.dumps({'error': str(e)})}
