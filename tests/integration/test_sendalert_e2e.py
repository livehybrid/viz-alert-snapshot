"""
Alert action end to end: fire the real alert actions from SPL with
`| sendalert`, through the REST search API, and inspect what the mock
receiver (docker/mock/mock_receiver.py) was actually sent.

Two triggers, both SPL, neither scheduled:
  * a saved search whose SPL ends in `| sendalert render_and_notify ...`,
    dispatched on demand through saved/searches/<name>/dispatch. sendalert
    then carries the saved search's name, which is how the action finds the
    destinations saved for it in the Visual Alerts config;
  * an ad hoc search ending in `| sendalert <action> param.to=...`, which has
    no search name, so only the param.to email fallback applies.

Every payload is decoded here with the standard library (json, email,
multipart via email.parser, PNG chunks via struct + zlib), never with the
app's own senders or helpers, and filtered by an id unique to the firing
(webhook path, recipient address, chat id, channel id), so the assertions do
not depend on what else the receiver saw.

Needs SPLUNK_MGMT_URL and the mock (MOCK_URL, default http://127.0.0.1:18080).
"""
from __future__ import annotations

import base64
import email
import email.policy
import hashlib
import json
import os
import ssl
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

import pytest

MGMT = os.environ.get("SPLUNK_MGMT_URL", "").rstrip("/")
USER = os.environ.get("SPLUNK_USER", "admin")
PW = os.environ.get("SPLUNK_PASSWORD", "Changeme1!")
MOCK = os.environ.get("MOCK_URL", "http://127.0.0.1:18080").rstrip("/")
# How Splunk (inside the compose network) reaches the mock.
MOCK_IN_NET = os.environ.get("MOCK_IN_NET_HOST", "mock")
APP = "viz-alert-snapshot"
NS = f"/servicesNS/nobody/{APP}"

pytestmark = pytest.mark.skipif(not MGMT, reason="SPLUNK_MGMT_URL not set, live tier skipped")

TELEGRAM_TOKEN = "123456789:CI-FAKE-TELEGRAM-TOKEN"
SLACK_TOKEN = "xoxb-ci-fake-slack-token"
WIDTH, HEIGHT = 640, 360

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


# --------------------------------------------------------------------------- clients

def splunk(method, path, form=None, body=None, params=None, user=USER, pw=PW, timeout=180):
    url = MGMT + path + ("?" + urllib.parse.urlencode(params) if params else "")
    headers = {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=_CTX, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def mock_records():
    with urllib.request.urlopen(MOCK + "/_deliveries", timeout=10) as r:
        return json.loads(r.read())


def wait_for(select, want, timeout=150, settle=8):
    """Poll the receiver until `select(records)` has `want` items, then wait
    `settle` seconds more and read again, so a duplicate delivery shows up."""
    deadline, got = time.time() + timeout, []
    while time.time() < deadline:
        got = select(mock_records())
        if len(got) >= want:
            break
        time.sleep(3)
    time.sleep(settle)
    return select(mock_records())


def body_of(rec):
    return base64.b64decode(rec["body_b64"])


def _wait_kv_ready(timeout=420):
    deadline, last = time.time() + timeout, None
    while time.time() < deadline:
        st, b = splunk("GET", "/services/kvstore/status", params={"output_mode": "json"})
        if st == 200:
            last = json.loads(b)["entry"][0]["content"].get("current", {}).get("status")
            if str(last).lower() == "ready":
                return
        time.sleep(5)
    pytest.fail(f"KV store not ready within {timeout}s (last {last!r})")


def _wait_job(sid, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st, b = splunk("GET", f"/services/search/jobs/{urllib.parse.quote(sid, safe='')}",
                       params={"output_mode": "json"})
        if st == 200:
            c = json.loads(b)["entry"][0]["content"]
            if c.get("isDone"):
                return c
        time.sleep(2)
    pytest.fail(f"job {sid} not done within {timeout}s")


# --------------------------------------------------------------------------- independent decoders

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_info(data):
    """Walk every PNG chunk, check each CRC, inflate IDAT and check the
    scanline count. Returns (width, height). Fails on anything malformed."""
    assert data[:8] == PNG_MAGIC, f"not a PNG: first bytes {data[:8]!r}"
    pos, width, height, idat, seen_iend, ctype, depth = 8, None, None, b"", False, None, None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        assert zlib.crc32(ctag + chunk) & 0xFFFFFFFF == crc, f"bad CRC on {ctag!r}"
        if ctag == b"IHDR":
            width, height, depth, ctype = struct.unpack(">IIBB", chunk[:10])
        elif ctag == b"IDAT":
            idat += chunk
        elif ctag == b"IEND":
            seen_iend = True
            break
        pos += 12 + length
    assert width and height and seen_iend, "PNG missing IHDR or IEND"
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    stride = 1 + (width * channels * depth + 7) // 8
    raw = zlib.decompress(idat)
    assert len(raw) == stride * height, f"IDAT holds {len(raw)} bytes, expected {stride * height}"
    return width, height


def assert_real_png(data):
    assert len(data) > 5000, f"suspiciously small PNG ({len(data)} bytes)"
    w, h = png_info(data)
    # Splunk's exporter screenshots the panel at the configured width; the
    # height includes the panel title, so it is at least the configured height.
    assert w == WIDTH, f"PNG is {w}x{h}, configured width {WIDTH}"
    assert HEIGHT <= h <= HEIGHT * 2, f"PNG is {w}x{h}, configured height {HEIGHT}"
    return data


def parse_multipart(rec):
    """Multipart body -> {name: (filename, content_type, bytes)} via email.parser."""
    ctype = rec["headers"]["content-type"]
    msg = email.message_from_bytes(
        b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body_of(rec),
        policy=email.policy.HTTP)
    assert msg.is_multipart(), f"not multipart: {ctype}"
    out = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        out[name] = (part.get_filename(), part.get_content_type(), part.get_payload(decode=True))
    return out


# --------------------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def ready():
    _wait_kv_ready()
    st, b = splunk("POST", "/services/admin/alert_actions/email",
                   form={"mailserver": f"{MOCK_IN_NET}:1025", "from": "splunk-ci@example.test",
                         "use_ssl": "0", "use_tls": "0"})
    assert st == 200, f"email settings -> {st}: {b[:300]}"
    st, b = splunk("POST", f"{NS}/viz_alert/settings",
                   body={"telegram_bot_token": TELEGRAM_TOKEN, "slack_bot_token": SLACK_TOKEN})
    assert st == 200 and json.loads(b)["creds_set"] == {"telegram_bot_token": True, "slack_bot_token": True}, b
    return True


def _save_config(name, destinations):
    st, b = splunk("POST", f"{NS}/viz_alert/config", body={
        "_key": name, "search_name": name, "app": "search", "owner": "admin",
        "viz_type": "splunk.line", "width": WIDTH, "height": HEIGHT, "theme": "dark",
        "options": {}, "destinations": destinations})
    assert st == 200, f"save config {name!r} -> {st}: {b[:300]}"


SPL_ROWS = ('| makeresults count=5 | streamstats count AS n '
            '| eval _time=relative_time(now(), "-1h@h") + n*300, count=n*n | table _time count')


def _fire_saved(name, sendalert):
    spl = f"{SPL_ROWS} | {sendalert}"
    path = f"/servicesNS/admin/search/saved/searches"
    splunk("DELETE", f"{path}/{urllib.parse.quote(name, safe='')}")
    st, b = splunk("POST", path, form={"name": name, "search": spl,
                                       "dispatch.earliest_time": "-24h", "dispatch.latest_time": "now"})
    assert st == 201, f"create saved search -> {st}: {b[:300]}"
    st, b = splunk("POST", f"{path}/{urllib.parse.quote(name, safe='')}/dispatch",
                   form={"output_mode": "json"})
    assert st == 201, f"dispatch -> {st}: {b[:300]}"
    return _wait_job(json.loads(b)["sid"])


@pytest.fixture(scope="module")
def all_channels(ready):
    """One saved search, five destinations, fired once."""
    tag = uuid.uuid4().hex[:10]
    name = f"VAS e2e all channels {tag}"  # spaces on purpose: real names have them
    ids = {
        "json": f"/hook/json-{tag}",
        "multipart": f"/hook/multipart-{tag}",
        "email": f"ops-{tag}@example.test",
        "chat_id": f"-100{int(tag[:8], 16)}",
        "channel": f"C{tag.upper()}",
        "name": name,
        "subject": f"VAS e2e: all channels {tag}",
        "message": "Five points, squared. Ünïcödé, \"quotes\" & <angles>",
    }
    _save_config(name, [
        {"type": "webhook", "url": f"http://{MOCK_IN_NET}:8080{ids['json']}"},
        {"type": "webhook", "url": f"http://{MOCK_IN_NET}:8080{ids['multipart']}", "mode": "multipart"},
        {"type": "email", "to": ids["email"]},
        {"type": "telegram", "chat_id": ids["chat_id"]},
        {"type": "slack", "channel": ids["channel"]},
    ])
    msg = ids["message"].replace('"', '\\"')
    job = _fire_saved(name, f'sendalert render_and_notify param.subject="{ids["subject"]}" '
                            f'param.message="{msg}"')
    assert int(job.get("resultCount", 0)) == 5, f"saved search returned {job.get('resultCount')} rows"
    # Wait for the last channel in the fan-out order to land.
    wait_for(lambda rs: [r for r in rs if r.get("host") == "slack.com"
                         and "completeUploadExternal" in r.get("path", "")
                         and ids["channel"] in body_of(r).decode("utf-8", "replace")], 1)
    return ids


def _hook(ids, kind):
    return [r for r in mock_records() if r["channel"] == "http" and r.get("path") == ids[kind]]


def _mail(addr):
    out = []
    for r in mock_records():
        if r["channel"] == "smtp" and any(addr in x for x in r["rcpts"]):
            out.append(email.message_from_bytes(body_of(r), policy=email.policy.default))
    return out


def _mail_png(msg):
    pngs = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert len(pngs) == 1, f"{len(pngs)} image/png parts in the email"
    return pngs[0].get_payload(decode=True)


def _telegram(ids):
    out = []
    for r in mock_records():
        if r.get("host") == "api.telegram.org":
            parts = parse_multipart(r)
            if parts.get("chat_id", (None, None, b""))[2].decode() == ids["chat_id"]:
                out.append((r, parts))
    return out


def _slack(ids):
    recs = [r for r in mock_records() if r.get("host") == "slack.com"]
    complete = [r for r in recs if "completeUploadExternal" in r["path"]
                and ids["channel"] in body_of(r).decode("utf-8", "replace")]
    return recs, complete


# --------------------------------------------------------------------------- saved search, every channel

def test_webhook_json(all_channels):
    recs = _hook(all_channels, "json")
    assert len(recs) == 1, f"{len(recs)} JSON webhook deliveries"
    r = recs[0]
    assert r["method"] == "POST" and r["headers"]["content-type"].startswith("application/json")
    doc = json.loads(body_of(r))
    assert doc["search_name"] == all_channels["name"]
    assert doc["subject"] == all_channels["subject"]
    assert doc["message"] == all_channels["message"]
    assert doc["viz_type"] == "splunk.line"
    assert_real_png(base64.b64decode(doc["image_png_b64"], validate=True))


def test_webhook_multipart(all_channels):
    recs = _hook(all_channels, "multipart")
    assert len(recs) == 1, f"{len(recs)} multipart webhook deliveries"
    parts = parse_multipart(recs[0])
    assert parts["search_name"][2].decode() == all_channels["name"]
    assert parts["subject"][2].decode() == all_channels["subject"]
    assert parts["message"][2].decode() == all_channels["message"]
    fname, ctype, data = parts["image"]
    assert (fname, ctype) == ("viz.png", "image/png")
    assert_real_png(data)


def test_email(all_channels):
    msgs = _mail(all_channels["email"])
    assert len(msgs) == 1, f"{len(msgs)} emails to {all_channels['email']}"
    m = msgs[0]
    assert m["Subject"] == all_channels["subject"]
    assert m["To"] == all_channels["email"]
    assert m["From"] == "splunk-ci@example.test"
    text = m.get_body(preferencelist=("plain",)).get_content()
    assert all_channels["message"] in text
    html = m.get_body(preferencelist=("html",)).get_content()
    assert "cid:snapshot" in html
    assert_real_png(_mail_png(m))


def test_telegram(all_channels):
    got = _telegram(all_channels)
    assert len(got) == 1, f"{len(got)} Telegram sendPhoto calls for chat {all_channels['chat_id']}"
    rec, parts = got[0]
    assert rec["method"] == "POST"
    assert rec["path"] == f"/bot{TELEGRAM_TOKEN}/sendPhoto"
    caption = parts["caption"][2].decode()
    assert all_channels["subject"] in caption and all_channels["message"] in caption
    fname, ctype, data = parts["photo"]
    assert (fname, ctype) == ("viz.png", "image/png")
    assert_real_png(data)


def test_slack(all_channels):
    recs, complete = _slack(all_channels)
    assert len(complete) == 1, f"{len(complete)} Slack completeUploadExternal calls"
    comp = json.loads(body_of(complete[0]))
    assert comp["channel_id"] == all_channels["channel"]
    assert comp["initial_comment"] == all_channels["message"]
    assert len(comp["files"]) == 1 and comp["files"][0]["title"] == all_channels["subject"]
    fid = comp["files"][0]["id"]
    uploads = [r for r in recs if r["path"] == f"/upload/{fid}"]
    assert len(uploads) == 1, f"{len(uploads)} uploads for file {fid}"
    reserve = [r for r in recs if "getUploadURLExternal" in r["path"]]
    # The reservation's length must match the bytes actually uploaded.
    data = assert_real_png(body_of(uploads[0]))
    q = [urllib.parse.parse_qs(urllib.parse.urlsplit(r["path"]).query) for r in reserve]
    assert any(x.get("length") == [str(len(data))] for x in q), f"no reservation for {len(data)} bytes: {q}"
    for r in [complete[0]] + reserve:
        assert r["headers"].get("authorization") == f"Bearer {SLACK_TOKEN}", r["path"]


def test_one_render_shared_by_every_channel(all_channels):
    """Render once, fan out: every channel carries the same PNG bytes."""
    digests = {
        "json": hashlib.sha256(base64.b64decode(json.loads(body_of(_hook(all_channels, "json")[0]))["image_png_b64"])).hexdigest(),
        "multipart": hashlib.sha256(parse_multipart(_hook(all_channels, "multipart")[0])["image"][2]).hexdigest(),
        "email": hashlib.sha256(_mail_png(_mail(all_channels["email"])[0])).hexdigest(),
        "telegram": hashlib.sha256(_telegram(all_channels)[0][1]["photo"][2]).hexdigest(),
    }
    assert len(set(digests.values())) == 1, digests


# --------------------------------------------------------------------------- ad hoc sendalert (no search name)

@pytest.fixture(scope="module")
def adhoc_email(ready, all_channels):
    """Ad hoc `| sendalert render_and_notify param.to=...` while a saved config
    exists (all_channels made one). An ad hoc search has no name, so the action
    must fall back to param.to, not trip over the saved configs."""
    tag = uuid.uuid4().hex[:10]
    addr, subject = f"adhoc-{tag}@example.test", f"VAS e2e ad hoc {tag}"
    st, b = splunk("POST", "/servicesNS/admin/search/search/jobs", form={
        "search": (f'{SPL_ROWS} | sendalert render_and_notify param.to="{addr}" param.subject="{subject}" '
                   f'param.width={WIDTH} param.height={HEIGHT}'),
        "exec_mode": "oneshot", "output_mode": "json", "earliest_time": "-24h", "latest_time": "now"})
    assert st == 200 and '"FATAL"' not in b, f"ad hoc sendalert -> {st}: {b[:400]}"
    wait_for(lambda rs: [r for r in rs if r["channel"] == "smtp" and any(addr in x for x in r["rcpts"])], 1)
    return addr, subject


def test_adhoc_sendalert_emails_param_to(adhoc_email):
    addr, subject = adhoc_email
    msgs = _mail(addr)
    assert len(msgs) == 1, f"{len(msgs)} emails to {addr}"
    assert msgs[0]["Subject"] == subject
    assert_real_png(_mail_png(msgs[0]))


def test_render_viz_email_action(ready):
    """The single-channel email action, also fired ad hoc."""
    tag = uuid.uuid4().hex[:10]
    addr, subject = f"single-{tag}@example.test", f"VAS e2e render_viz_email {tag}"
    st, b = splunk("POST", "/servicesNS/admin/search/search/jobs", form={
        "search": (f'{SPL_ROWS} | sendalert render_viz_email param.to="{addr}" param.subject="{subject}" '
                   f'param.width={WIDTH} param.height={HEIGHT} param.viz_type="splunk.column"'),
        "exec_mode": "oneshot", "output_mode": "json", "earliest_time": "-24h", "latest_time": "now"})
    assert st == 200 and '"FATAL"' not in b, f"sendalert render_viz_email -> {st}: {b[:400]}"
    wait_for(lambda rs: [r for r in rs if r["channel"] == "smtp" and any(addr in x for x in r["rcpts"])], 1)
    msgs = _mail(addr)
    assert len(msgs) == 1, f"{len(msgs)} emails to {addr}"
    assert msgs[0]["Subject"] == subject
    assert_real_png(_mail_png(msgs[0]))


# --------------------------------------------------------------------------- RBAC

def _fire_as(user, pw, role, addr):
    st, b = splunk("POST", "/services/authentication/users", form={
        "name": user, "password": pw, "roles": role})
    assert st in (201, 409), f"create user {user} -> {st}: {b[:300]}"
    splunk("POST", f"/servicesNS/{user}/search/search/jobs", form={
        "search": f'{SPL_ROWS} | sendalert render_and_notify param.to="{addr}"',
        "exec_mode": "oneshot", "output_mode": "json"}, user=user, pw=pw)


def _mails_to(addr, **kw):
    return wait_for(lambda rs: [r for r in rs if r["channel"] == "smtp"
                                and any(addr in x for x in r["rcpts"])], 1, **kw)


def test_user_without_capability_delivers_nothing(ready):
    """Role `user` has no run_visual_alert: sendalert runs, the execute
    endpoint refuses it, nothing reaches any channel."""
    addr = f"denied-{uuid.uuid4().hex[:10]}@example.test"
    _fire_as("vas_plain", "Vas-plain-pw-2026!", "user", addr)
    got = _mails_to(addr, timeout=60, settle=0)
    assert got == [], f"{len(got)} emails delivered for a user without run_visual_alert"


def test_user_with_capability_delivers(ready):
    """Positive control for the refusal above: the same SPL from a non-admin
    role that has run_visual_alert (power) is delivered exactly once."""
    addr = f"allowed-{uuid.uuid4().hex[:10]}@example.test"
    _fire_as("vas_power", "Vas-power-pw-2026!", "power", addr)
    got = _mails_to(addr)
    assert len(got) == 1, f"{len(got)} emails delivered for a power user"
