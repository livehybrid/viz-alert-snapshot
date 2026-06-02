"""
Generic webhook sender — POST the rendered viz to any HTTP endpoint.

Two modes:
  json      (default): application/json with the PNG base64-encoded — good for
            custom integrations, serverless functions, MS Teams workflow flows, etc.
  multipart: multipart/form-data with the PNG as a file part — good for endpoints
            that expect a file upload.

The URL may itself carry a secret token (per destination). For hardening, move
secrets to storage/passwords later (see docs).
"""
import base64
from . import _http

TYPE = 'webhook'
LABEL = 'Webhook'
DEST_FIELDS = [('url', 'Webhook URL', True), ('mode', 'Mode (json|multipart)', False)]
CRED_KEYS = []


def send(dest, png_bytes, ctx):
    url = (dest.get('url') or '').strip()
    mode = (dest.get('mode') or 'json').strip().lower()
    if not url:
        return False, 'destination missing url'
    try:
        if mode == 'multipart':
            status, text = _http.post_multipart(
                url,
                fields={'search_name': ctx.get('search_name', ''),
                        'subject': ctx.get('subject', ''),
                        'message': ctx.get('body', ''),
                        'viz_type': ctx.get('viz_type', '')},
                files={'image': ('viz.png', png_bytes, 'image/png')})
        else:
            status, text = _http.post_json(url, {
                'search_name': ctx.get('search_name', ''),
                'subject': ctx.get('subject', ''),
                'message': ctx.get('body', ''),
                'viz_type': ctx.get('viz_type', ''),
                'image_png_b64': base64.b64encode(png_bytes).decode('ascii'),
            })
        if 200 <= status < 300:
            return True, 'sent (%d)' % status
        return False, 'webhook http %d: %s' % (status, text[:200])
    except Exception as e:
        return False, 'webhook error: %s' % e
