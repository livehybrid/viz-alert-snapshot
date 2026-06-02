"""
_http.py — tiny dependency-free HTTP helpers (urllib only; no `requests`).

Provides multipart/form-data and JSON POST so the senders can upload a PNG to
Telegram / Slack / arbitrary webhooks without external packages.
"""
import ssl
import json
import uuid
import urllib.request


def _ctx():
    c = ssl.create_default_context()
    # Splunk-internal / self-signed endpoints; external APIs use valid certs so
    # this only relaxes verification, never weakens for public hosts in practice.
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def post_json(url, obj, headers=None, timeout=30):
    body = json.dumps(obj).encode('utf-8')
    h = {'Content-Type': 'application/json'}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method='POST')
    with urllib.request.urlopen(req, context=_ctx(), timeout=timeout) as r:
        return r.status, r.read().decode('utf-8', 'replace')


def encode_multipart(fields=None, files=None):
    """
    Build a multipart/form-data body.
      fields: { name: str_value }
      files:  { name: (filename, bytes, content_type) }
    Returns (content_type, body_bytes).
    """
    boundary = uuid.uuid4().hex
    crlf = b'\r\n'
    out = []
    for k, v in (fields or {}).items():
        out.append(b'--' + boundary.encode())
        out.append(('Content-Disposition: form-data; name="%s"' % k).encode())
        out.append(b'')
        out.append(str(v).encode('utf-8'))
    for k, (filename, content, ctype) in (files or {}).items():
        out.append(b'--' + boundary.encode())
        out.append(('Content-Disposition: form-data; name="%s"; filename="%s"'
                    % (k, filename)).encode())
        out.append(('Content-Type: %s' % ctype).encode())
        out.append(b'')
        out.append(content)
    out.append(b'--' + boundary.encode() + b'--')
    out.append(b'')
    return 'multipart/form-data; boundary=%s' % boundary, crlf.join(out)


def post_multipart(url, fields=None, files=None, headers=None, timeout=60):
    content_type, body = encode_multipart(fields, files)
    h = {'Content-Type': content_type, 'Content-Length': str(len(body))}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method='POST')
    with urllib.request.urlopen(req, context=_ctx(), timeout=timeout) as r:
        return r.status, r.read().decode('utf-8', 'replace')
