"""Telegram sender — Bot API sendPhoto (multipart upload of the PNG)."""
import json
from . import _http

TYPE = 'telegram'
LABEL = 'Telegram'
# Fields the UI collects per destination, plus channel-level creds it needs.
DEST_FIELDS = [('chat_id', 'Chat ID', True)]
CRED_KEYS = ['telegram_bot_token']


def send(dest, png_bytes, ctx):
    token = (ctx.get('creds') or {}).get('telegram_bot_token')
    chat_id = (dest.get('chat_id') or '').strip()
    if not token:
        return False, 'telegram_bot_token not configured (Channels settings)'
    if not chat_id:
        return False, 'destination missing chat_id'

    caption = ('*%s*\n%s' % (ctx.get('subject', ''), ctx.get('body', ''))).strip()
    url = 'https://api.telegram.org/bot%s/sendPhoto' % token
    try:
        status, text = _http.post_multipart(
            url,
            fields={'chat_id': chat_id, 'caption': caption[:1024], 'parse_mode': 'Markdown'},
            files={'photo': ('viz.png', png_bytes, 'image/png')},
        )
        ok = False
        try:
            ok = json.loads(text).get('ok', False)
        except ValueError:
            pass
        return (True, 'sent') if ok else (False, 'telegram api: %s' % text[:200])
    except Exception as e:
        return False, 'telegram error: %s' % e
