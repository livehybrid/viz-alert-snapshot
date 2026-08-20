"""
Live integration — the REST endpoints respond and the preview pipeline renders
a REAL PNG through Splunk's bundled Chromium (splunk-visual-exporter).

Runs against any reachable Splunk with the app installed (the CI docker
harness, or a live dev instance). Skips entirely unless SPLUNK_MGMT_URL is set,
so the hermetic unit suite stays fast and Splunk-free.

  SPLUNK_MGMT_URL   e.g. https://127.0.0.1:8089
  SPLUNK_USER       default admin
  SPLUNK_PASSWORD   default Changeme1!
"""
from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.request

import pytest

MGMT = os.environ.get("SPLUNK_MGMT_URL", "").rstrip("/")
USER = os.environ.get("SPLUNK_USER", "admin")
PW = os.environ.get("SPLUNK_PASSWORD", "Changeme1!")
APP = "viz-alert-snapshot"
NS = f"/servicesNS/nobody/{APP}"

pytestmark = pytest.mark.skipif(not MGMT, reason="SPLUNK_MGMT_URL not set — live tier skipped")

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _request(method, path, body=None, timeout=180):
    auth = base64.b64encode(f"{USER}:{PW}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(MGMT + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=_CTX, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.mark.parametrize("endpoint", ["config", "settings"])
def test_endpoint_responds(endpoint):
    """restmap wiring + handler import: the persistent handlers answer."""
    status, body = _request("GET", f"{NS}/viz_alert/{endpoint}?output_mode=json")
    assert status == 200, f"{endpoint} -> {status}: {body[:300]}"


def test_preview_renders_real_png():
    """The whole render pipeline: rows -> ds.test definition -> bundled
    Chromium -> PNG. This is the app's entire reason to exist."""
    payload = {
        "viz_type": "splunk.line",
        "options": {},
        "width": 600,
        "height": 400,
        "theme": "dark",
        "title": "integration render",
        "data_strategy": "sample",
        "rows": [
            {"_time": "2026-08-20T08:00:00.000Z", "count": 4},
            {"_time": "2026-08-20T08:05:00.000Z", "count": 9},
            {"_time": "2026-08-20T08:10:00.000Z", "count": 2},
        ],
    }
    status, body = _request("POST", f"{NS}/viz_alert/preview", body=payload)
    assert status == 200, f"preview -> {status}: {body[:400]}"
    obj = json.loads(body)
    png_b64 = obj.get("png_b64", "")
    assert png_b64, f"no png_b64 in response; notes={obj.get('notes')}"
    png = base64.b64decode(png_b64)
    assert png.startswith(b"\x89PNG\r\n"), f"not a PNG (first bytes {png[:8]!r})"
    assert len(png) > 5000, f"suspiciously small render ({len(png)} bytes)"
    assert obj.get("processed", {}).get("total") == 3, "processed rows went missing"
