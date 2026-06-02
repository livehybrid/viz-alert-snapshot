"""Email sender — reuses Splunk's configured [email] settings + inline PNG."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import mailer  # noqa: E402

TYPE = 'email'
LABEL = 'Email'
DEST_FIELDS = [('to', 'Recipients (comma-separated)', True)]
CRED_KEYS = []


def send(dest, png_bytes, ctx):
    to = [a.strip() for a in (dest.get('to', '') or '').replace(';', ',').split(',') if a.strip()]
    if not to:
        return False, 'destination missing recipients'
    if not ctx.get('server_uri') or not ctx.get('session_key'):
        return False, 'no server_uri/session_key for email settings'
    try:
        settings = mailer.get_email_settings(ctx['server_uri'], ctx['session_key'])
        encrypted = mailer.send_snapshot(settings, to, ctx.get('subject', 'Splunk Alert'),
                                         ctx.get('body', ''), png_bytes)
        if encrypted:
            return True, 'sent (unauthenticated — Splunk email password is encrypted)'
        return True, 'sent via %s' % settings.get('mailserver')
    except Exception as e:
        return False, 'email error: %s' % e
