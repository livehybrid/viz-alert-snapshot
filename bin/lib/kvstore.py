"""
kvstore.py — KV store client for the alert_viz_configs collection.

Uses splunk.rest.simpleRequest, which connects to the local management port with
TLS **verified against Splunk's configured CA** (no disabled verification). Its
`jsonargs` parameter sends a raw JSON body with the right Content-Type, which is
exactly what the KV store's batch_save endpoint requires.
"""
import json

APP = 'viz-alert-snapshot'
COLLECTION = 'alert_viz_configs'


def _json(content, what):
    """Decode a KV store response, naming the body if it is not JSON.

    Splunk 10.6 (Postgres-backed KV store) answered GET .../data/<collection>
    with a body json.loads could not parse, where 10.4 returned JSON, so every
    read now asks for output_mode=json explicitly.
    """
    if not content:
        return None
    if isinstance(content, bytes):
        content = content.decode('utf-8', 'replace')
    try:
        return json.loads(content)
    except ValueError:
        raise ValueError('KV store %s returned non-JSON: %r' % (what, content[:300]))


def _base(owner='nobody'):
    return '/servicesNS/%s/%s/storage/collections/data/%s' % (owner, APP, COLLECTION)


def query(session_key, query_obj=None, owner='nobody'):
    import splunk.rest as rest
    getargs = {'output_mode': 'json'}
    if query_obj:
        getargs['query'] = json.dumps(query_obj)
    _, content = rest.simpleRequest(_base(owner), sessionKey=session_key,
                                    getargs=getargs, method='GET')
    return _json(content, 'query') or []


def get(session_key, key, owner='nobody'):
    import splunk.rest as rest
    _, content = rest.simpleRequest('%s/%s' % (_base(owner), key),
                                    sessionKey=session_key, getargs={'output_mode': 'json'},
                                    method='GET')
    return _json(content, 'get')


def upsert(session_key, doc, owner='nobody'):
    """Create-or-update via batch_save (raw JSON array body via jsonargs)."""
    import splunk.rest as rest
    _, content = rest.simpleRequest('%s/batch_save' % _base(owner), sessionKey=session_key,
                                    jsonargs=json.dumps([doc]), method='POST')
    return _json(content, 'batch_save')


def delete(session_key, key, owner='nobody'):
    import splunk.rest as rest
    rest.simpleRequest('%s/%s' % (_base(owner), key), sessionKey=session_key, method='DELETE')
