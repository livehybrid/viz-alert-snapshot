"""TEMPORARY discovery, removed before merge."""
import base64
import json
import os
import time
import urllib.parse
import urllib.request

import pytest

from test_live_render import _request, MGMT, NS

pytestmark = pytest.mark.skipif(not MGMT, reason="no splunk")
MOCK = "http://127.0.0.1:18080"


def _form(method, path, data):
    import ssl
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    auth = base64.b64encode(b"admin:Changeme1!").decode()
    req = urllib.request.Request(MGMT + path, data=urllib.parse.urlencode(data).encode(), method=method,
                                 headers={"Authorization": "Basic " + auth})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=180) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_discover():
    out = []
    st, b = _request("POST", f"{NS}/viz_alert/preview", body={"viz_type": "splunk.line", "width": 300, "height": 200,
                     "rows": [{"_time": "2026-08-20T08:00:00.000Z", "count": 4}, {"_time": "2026-08-20T08:05:00.000Z", "count": 9}]})
    out.append(f"preview {st} {b[:300]!r}")
    out.append(str(_form("POST", "/services/admin/alert_actions/email", {"mailserver": "mock:1025", "from": "ci@splunk.test"})[0]))
    st, b = _request("POST", f"{NS}/viz_alert/settings", body={"telegram_bot_token": "123:TESTTOKEN", "slack_bot_token": "xoxb-test"})
    out.append(f"settings {st} {b[:200]!r}")
    dests = [{"type": "webhook", "url": "http://mock:8080/hook/json"}, {"type": "webhook", "url": "http://mock:8080/hook/mp", "mode": "multipart"},
             {"type": "email", "to": "saved@ci.test"}, {"type": "telegram", "chat_id": "42"}, {"type": "slack", "channel": "C123"}]
    st, b = _request("POST", f"{NS}/viz_alert/config", body={"_key": "vas_disc_saved", "search_name": "vas_disc_saved", "viz_type": "splunk.line", "destinations": dests})
    out.append(f"config {st} {b[:200]!r}")
    urllib.request.urlopen(urllib.request.Request(MOCK + "/_deliveries", method="DELETE"))
    spl = '| makeresults count=3 | streamstats count | eval _time=_time-count*60 | table _time count | sendalert render_and_notify param.to="adhoc@ci.test" param.subject="Disc adhoc"'
    st, b = _form("POST", "/servicesNS/admin/search/search/jobs", {"search": spl, "exec_mode": "oneshot", "output_mode": "json"})
    out.append(f"adhoc {st} {b[:400]}")
    st, b = _form("POST", "/servicesNS/admin/search/saved/searches", {"name": "vas_disc_saved", "search": spl.replace("adhoc@", "saved2@")})
    out.append(f"saved create {st}")
    st, b = _form("POST", "/servicesNS/admin/search/saved/searches/vas_disc_saved/dispatch", {"output_mode": "json"})
    out.append(f"dispatch {st} {b[:200]}")
    time.sleep(60)
    recs = json.loads(urllib.request.urlopen(MOCK + "/_deliveries").read())
    for r in recs:
        body = base64.b64decode(r["body_b64"])
        out.append(f"REC {r['channel']} {r.get('host')} {r.get('method')} {r.get('path')} {r.get('rcpts')} len={len(body)} {body[:200]!r}")
    st, b = _form("POST", "/services/search/jobs", {"search": "search index=_internal (source=*viz_alert_snapshot.log OR sendmodalert OR render_and_notify) earliest=-10m | head 40 | table _raw", "exec_mode": "oneshot", "output_mode": "json", "count": "40"})
    try:
        for r in json.loads(b).get("results", []):
            out.append("LOG " + r["_raw"][:400])
    except Exception as e:
        out.append(f"log err {e} {b[:200]}")
    raise AssertionError("\n".join(out))
