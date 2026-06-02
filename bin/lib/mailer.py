"""mailer.py — read Splunk's configured email settings and send a PNG snapshot."""
import json
import ssl
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage
from html import escape as _html_escape


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _splunkd_get(server_uri, session_key, path, params=None):
    url = server_uri.rstrip('/') + path
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Authorization': 'Splunk ' + session_key})
    with urllib.request.urlopen(req, context=_ctx(), timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


def _decrypt(val):
    """Decrypt a Splunk-encrypted value ($1$/$7$…) the way core sendemail does."""
    if not val:
        return ''
    try:
        from splunk.clilib import cli_common
        out = cli_common.decrypt(val, setEnv=True, ignoreErrors=True)
        return out if out is not None else ''
    except Exception:
        return ''  # can't decrypt here -> caller will send without auth


def get_email_settings(server_uri, session_key):
    """
    Read Splunk's [email] alert-action settings and DECRYPT the SMTP password,
    mirroring core sendemail: the admin/alert_actions EAI endpoint exposes
    `clear_password` (still encrypted) which cli_common.decrypt() turns into the
    real password. Requires an admin/system token (we pass the system token).
    """
    truthy = ('1', 'true', 'True', True)
    c = {}
    # Prefer the Python EAI (same path sendemail uses); fall back to REST.
    try:
        import splunk.entity as entity
        c = dict(entity.getEntity('admin/alert_actions', 'email',
                                  owner='nobody', sessionKey=session_key))
    except Exception:
        for path in ('/services/admin/alert_actions/email',
                     '/services/configs/conf-alert_actions/email'):
            try:
                data = _splunkd_get(server_uri, session_key, path, {'output_mode': 'json'})
                c = (data.get('entry') or [{}])[0].get('content', {})
                if c:
                    break
            except Exception:
                continue

    raw_pw = c.get('clear_password') or c.get('auth_password') or ''
    return {
        'mailserver': c.get('mailserver') or 'localhost:25',
        'from': c.get('from') or 'splunk@localhost',
        'use_ssl': c.get('use_ssl') in truthy,
        'use_tls': c.get('use_tls') in truthy,
        'auth_username': c.get('auth_username') or '',
        'auth_password': _decrypt(raw_pw),
    }


def send_snapshot(settings, to_addrs, subject, body_text, png_bytes, cid='snapshot'):
    msg = EmailMessage()
    msg['From'] = settings['from']
    msg['To'] = ', '.join(to_addrs)
    msg['Subject'] = subject
    msg.set_content(body_text)
    safe_body = _html_escape(body_text).replace('\n', '<br>')
    html = ("<html><body><p>%s</p>"
            "<img src='cid:%s' style='max-width:100%%;border:1px solid #2a2a3a'/>"
            "</body></html>" % (safe_body, cid))
    msg.add_alternative(html, subtype='html')
    msg.get_payload()[1].add_related(png_bytes, 'image', 'png',
                                     cid='<%s>' % cid, filename='snapshot.png')

    host, _, port = settings['mailserver'].partition(':')
    port = int(port or (465 if settings['use_ssl'] else 25))
    encrypted = settings['auth_password'].startswith('$')  # Splunk-encrypted -> unusable here
    if settings['use_ssl']:
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=_ctx())
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        if settings['use_tls']:
            server.starttls(context=_ctx())
    try:
        if settings['auth_username'] and settings['auth_password'] and not encrypted:
            server.login(settings['auth_username'], settings['auth_password'])
        server.send_message(msg)
    finally:
        server.quit()
    return encrypted  # caller can warn if auth was configured but unusable
