"""
secrets.py — channel credentials in Splunk's encrypted storage/passwords.

Tokens (Telegram bot token, Slack bot token) are never stored in the KV config
or returned to the UI in clear text — only here, encrypted at rest by Splunk.
"""
import json
from urllib.parse import quote

APP = 'viz-alert-snapshot'
REALM = 'viz_alert_channel'

_BASE = '/servicesNS/nobody/%s/storage/passwords' % APP


def _entry(name):
    return '%s/%s' % (_BASE, quote('%s:%s:' % (REALM, name), safe=''))


def get_creds(session_key):
    """Return { cred_name: clear_value } for our realm."""
    import splunk.rest as rest
    _, content = rest.simpleRequest(
        _BASE, sessionKey=session_key,
        getargs={'output_mode': 'json', 'count': 0})
    out = {}
    for e in json.loads(content).get('entry', []):
        c = e.get('content', {})
        if c.get('realm') == REALM:
            out[c.get('username')] = c.get('clear_password', '')
    return out


def set_cred(session_key, name, value):
    """Create or update a credential."""
    import splunk.rest as rest
    try:
        rest.simpleRequest(_entry(name), sessionKey=session_key,
                           postargs={'password': value}, method='POST')
        return
    except Exception:
        pass  # not present yet -> create
    rest.simpleRequest(_BASE, sessionKey=session_key,
                       postargs={'name': name, 'password': value, 'realm': REALM},
                       method='POST')


def delete_cred(session_key, name):
    import splunk.rest as rest
    rest.simpleRequest(_entry(name), sessionKey=session_key, method='DELETE')
