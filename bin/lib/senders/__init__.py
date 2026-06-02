"""
senders — channel dispatch registry.

Each sender module exposes: TYPE, LABEL, DEST_FIELDS, CRED_KEYS, send(dest, png, ctx).
`dispatch()` renders-once/fans-out: given a list of destination dicts, it calls
the matching sender for each and returns per-destination results.
"""
from . import email_sender, telegram, slack, webhook

_REGISTRY = {m.TYPE: m for m in (email_sender, telegram, slack, webhook)}


def _field(f):
    d = {'name': f[0], 'label': f[1], 'required': f[2]}
    if len(f) > 3 and f[3]:
        d['options'] = list(f[3])
    return d


def registry():
    """UI-facing metadata: which channels exist and what fields/creds they need."""
    return [
        {'type': m.TYPE, 'label': m.LABEL,
         'fields': [_field(f) for f in m.DEST_FIELDS],
         'cred_keys': list(m.CRED_KEYS)}
        for m in (email_sender, telegram, slack, webhook)
    ]


def all_cred_keys():
    keys = []
    for m in _REGISTRY.values():
        for k in m.CRED_KEYS:
            if k not in keys:
                keys.append(k)
    return keys


def dispatch(destinations, png_bytes, ctx):
    """Send to every destination. Returns [{type, target, ok, detail}, ...]."""
    results = []
    for dest in destinations or []:
        t = dest.get('type')
        mod = _REGISTRY.get(t)
        if not mod:
            results.append({'type': t, 'ok': False, 'detail': 'unknown destination type'})
            continue
        ok, detail = mod.send(dest, png_bytes, ctx)
        results.append({'type': t, 'ok': ok, 'detail': detail,
                        'target': dest.get('to') or dest.get('chat_id')
                        or dest.get('channel') or dest.get('url')})
    return results
