"""mailer.py — read Splunk's configured email settings and send a PNG snapshot.

- Email settings are read via Splunk's own EAI/REST (TLS verified against Splunk's
  CA); the SMTP password is decrypted exactly like core sendemail.
- The SMTP connection to the configured relay uses a lenient TLS context, matching
  Splunk's own email behaviour (Splunk does not verify the relay certificate, and
  we reuse the operator's Splunk email configuration). This is the one place we
  don't strictly verify, and it is scoped to the relay only.
"""
import ssl
import json
import smtplib
from email.message import EmailMessage
from html import escape as _html_escape


def _smtp_context():
    # Lenient — matches core Splunk email (relays are often internal/self-signed).
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


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
    # Prefer the Python EAI (same path sendemail uses); both go through Splunk's
    # REST layer with TLS verified against Splunk's configured CA.
    try:
        import splunk.entity as entity
        c = dict(entity.getEntity('admin/alert_actions', 'email',
                                  owner='nobody', sessionKey=session_key))
    except Exception:
        try:
            import splunk.rest as rest
            _, content = rest.simpleRequest('/services/admin/alert_actions/email',
                                            sessionKey=session_key,
                                            getargs={'output_mode': 'json'}, method='GET')
            c = (json.loads(content).get('entry') or [{}])[0].get('content', {})
        except Exception:
            c = {}

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
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=_smtp_context())
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        if settings['use_tls']:
            server.starttls(context=_smtp_context())
    try:
        if settings['auth_username'] and settings['auth_password'] and not encrypted:
            server.login(settings['auth_username'], settings['auth_password'])
        server.send_message(msg)
    finally:
        server.quit()
    return encrypted  # caller can warn if auth was configured but unusable
