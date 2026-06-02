"""
kvstore.py — minimal KV store client for the alert_viz_configs collection.

KV store's data endpoints require a **raw JSON body** with
`Content-Type: application/json`. splunk.rest.simpleRequest with postargs sends
form-encoded data and the KV store rejects it ("Must supply 'Content-Type'") —
so we use http.client with explicit headers (per the splunk-react-app skill).
"""
import ssl
import json
import http.client

APP = 'viz-alert-snapshot'
COLLECTION = 'alert_viz_configs'


def _conn(splunkd_host='127.0.0.1', splunkd_port=8089):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return http.client.HTTPSConnection(splunkd_host, splunkd_port, context=ctx, timeout=30)


def _base(owner='nobody'):
    return '/servicesNS/%s/%s/storage/collections/data/%s' % (owner, APP, COLLECTION)


def _request(method, path, session_key, body=None):
    conn = _conn()
    headers = {
        'Authorization': 'Splunk ' + session_key,
        'Content-Type': 'application/json',
    }
    payload = json.dumps(body).encode('utf-8') if body is not None else None
    if payload is not None:
        headers['Content-Length'] = str(len(payload))
    try:
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode('utf-8')
        if resp.status >= 400:
            raise RuntimeError('KV %s %s -> %s: %s' % (method, path, resp.status, raw[:300]))
        return json.loads(raw) if raw.strip() else None
    finally:
        conn.close()


def query(session_key, query_obj=None, owner='nobody'):
    path = _base(owner)
    if query_obj:
        path += '?query=' + json.dumps(query_obj)
    return _request('GET', path, session_key) or []


def get(session_key, key, owner='nobody'):
    return _request('GET', _base(owner) + '/' + key, session_key)


def upsert(session_key, doc, owner='nobody'):
    """Create-or-update via batch_save (raw JSON array body)."""
    return _request('POST', _base(owner) + '/batch_save', session_key, body=[doc])


def delete(session_key, key, owner='nobody'):
    return _request('DELETE', _base(owner) + '/' + key, session_key)
