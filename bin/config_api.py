"""
config_api.py — persistent REST handler: CRUD for alert_viz_configs (KV store).

Routes by HTTP method + optional key in the path:
  GET    /viz_alert/config            -> list all configs
  GET    /viz_alert/config/<key>      -> one config (200 + {_key} if missing, for create flow)
  POST   /viz_alert/config            -> upsert (body is the config doc)
  DELETE /viz_alert/config/<key>      -> delete

A config doc:
  {
    "_key":         "<saved search name>",   # we key by saved search
    "search_name":  "...", "app": "...", "owner": "...",
    "viz_type":     "splunk.line", "options": {...},
    "width": 800, "height": 450, "theme": "dark",
    "data_strategy": "search" | "sample",
    "destinations": [ {type, ...}, ... ]
  }
"""
import os
import sys
import json
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import kvstore  # noqa: E402

from splunk.persistconn.application import PersistentServerConnectionApplication  # noqa: E402

logging.basicConfig(
    filename=os.path.join(os.environ.get('SPLUNK_HOME', '/opt/splunk'),
                          'var', 'log', 'splunk', 'viz_alert_snapshot.log'),
    level=logging.INFO,
    format='%(asctime)s config_api %(levelname)s %(message)s')
log = logging.getLogger('viz_alert_config')


def _key_from_path(rest_path):
    # rest_path like "/viz_alert/config" or "/viz_alert/config/<key>"
    parts = [p for p in (rest_path or '').split('/') if p]
    if len(parts) >= 3:  # viz_alert, config, <key>
        return '/'.join(parts[2:])
    return None


class ConfigHandler(PersistentServerConnectionApplication):
    def __init__(self, command_line=None, command_arg=None):
        super().__init__()

    def handle(self, in_string):
        try:
            req = json.loads(in_string)
            session_key = (req.get('session') or {}).get('authtoken')
            if not session_key:
                return {'status': 401, 'payload': json.dumps({'error': 'no session'})}
            method = (req.get('method') or 'GET').upper()
            key = _key_from_path(req.get('rest_path'))

            if method == 'GET':
                if key:
                    try:
                        doc = kvstore.get(session_key, key)
                        return {'status': 200, 'payload': json.dumps(doc)}
                    except Exception as e:
                        # missing doc -> 200 + {_key} so the UI opens a create form
                        if any(s in str(e) for s in ('404', 'not find', 'Could not find')):
                            return {'status': 200, 'payload': json.dumps({'_key': key})}
                        raise
                return {'status': 200, 'payload': json.dumps(kvstore.query(session_key))}

            if method == 'POST':
                doc = json.loads(req.get('payload') or '{}')
                if not doc.get('_key') and doc.get('search_name'):
                    doc['_key'] = doc['search_name']
                if not doc.get('_key'):
                    return {'status': 400, 'payload': json.dumps(
                        {'error': 'config requires _key or search_name'})}
                kvstore.upsert(session_key, doc)
                return {'status': 200, 'payload': json.dumps({'_key': doc['_key'], 'ok': True})}

            if method == 'DELETE':
                if not key:
                    return {'status': 400, 'payload': json.dumps({'error': 'delete requires a key'})}
                kvstore.delete(session_key, key)
                return {'status': 200, 'payload': json.dumps({'_key': key, 'deleted': True})}

            return {'status': 405, 'payload': json.dumps({'error': 'method not allowed'})}
        except Exception as e:
            log.exception('config_api failed')
            return {'status': 500, 'payload': json.dumps({'error': str(e)})}
