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


def _base(owner='nobody'):
    return '/servicesNS/%s/%s/storage/collections/data/%s' % (owner, APP, COLLECTION)


def query(session_key, query_obj=None, owner='nobody'):
    import splunk.rest as rest
    getargs = {}
    if query_obj:
        getargs['query'] = json.dumps(query_obj)
    _, content = rest.simpleRequest(_base(owner), sessionKey=session_key,
                                    getargs=getargs, method='GET')
    return json.loads(content) if content else []


def get(session_key, key, owner='nobody'):
    import splunk.rest as rest
    _, content = rest.simpleRequest('%s/%s' % (_base(owner), key),
                                    sessionKey=session_key, method='GET')
    return json.loads(content) if content else None


def upsert(session_key, doc, owner='nobody'):
    """Create-or-update via batch_save (raw JSON array body via jsonargs)."""
    import splunk.rest as rest
    _, content = rest.simpleRequest('%s/batch_save' % _base(owner), sessionKey=session_key,
                                    jsonargs=json.dumps([doc]), method='POST')
    return json.loads(content) if content else None


def delete(session_key, key, owner='nobody'):
    import splunk.rest as rest
    rest.simpleRequest('%s/%s' % (_base(owner), key), sessionKey=session_key, method='DELETE')
