"""
Slack sender — uploads the PNG to a channel.

Uses the modern external-upload flow (files.getUploadURLExternal ->
PUT bytes -> files.completeUploadExternal), since the legacy files.upload is
being sunset. Needs a bot token (xoxb-...) with files:write + the channel id.
"""
import json
import urllib.request
from . import _http

TYPE = 'slack'
LABEL = 'Slack'
DEST_FIELDS = [('channel', 'Channel ID', True)]
CRED_KEYS = ['slack_bot_token']

_API = 'https://slack.com/api/'


def _get(url, token, timeout=30):
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer %s' % token})
    with urllib.request.urlopen(req, context=_http._ctx(), timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def send(dest, png_bytes, ctx):
    token = (ctx.get('creds') or {}).get('slack_bot_token')
    channel = (dest.get('channel') or '').strip()
    if not token:
        return False, 'slack_bot_token not configured (Channels settings)'
    if not channel:
        return False, 'destination missing channel id'

    title = ctx.get('subject', 'Splunk visualization')
    comment = ctx.get('body', '')
    try:
        # 1) reserve an upload URL
        length = len(png_bytes)
        info = _get('%sfiles.getUploadURLExternal?filename=viz.png&length=%d'
                    % (_API, length), token)
        if not info.get('ok'):
            return False, 'getUploadURLExternal: %s' % info.get('error')
        upload_url, file_id = info['upload_url'], info['file_id']

        # 2) PUT the bytes to the returned URL
        req = urllib.request.Request(upload_url, data=png_bytes, method='POST')
        with urllib.request.urlopen(req, context=_http._ctx(), timeout=60) as r:
            r.read()

        # 3) complete the upload, sharing into the channel
        status, text = _http.post_json(
            '%sfiles.completeUploadExternal' % _API,
            {'files': [{'id': file_id, 'title': title}],
             'channel_id': channel, 'initial_comment': comment},
            headers={'Authorization': 'Bearer %s' % token})
        res = json.loads(text)
        return (True, 'sent') if res.get('ok') else (False, 'complete: %s' % res.get('error'))
    except Exception as e:
        return False, 'slack error: %s' % e
