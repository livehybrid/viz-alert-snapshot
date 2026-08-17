"""Unit tests for the channel senders and the dispatch registry.

Every sender uses only urllib via senders._http, so we mock at that seam and
never touch the network.
"""
import json

import senders
from senders import _http, telegram, webhook


# --- registry metadata ------------------------------------------------------

def test_registry_lists_all_channels():
    types = {c["type"] for c in senders.registry()}
    assert types == {"email", "telegram", "slack", "webhook"}
    for chan in senders.registry():
        assert "label" in chan and "fields" in chan and "cred_keys" in chan


def test_all_cred_keys_deduped():
    keys = senders.all_cred_keys()
    assert "telegram_bot_token" in keys
    assert len(keys) == len(set(keys))  # no duplicates


# --- dispatch ---------------------------------------------------------------

def test_dispatch_unknown_type_reports_error():
    out = senders.dispatch([{"type": "carrier-pigeon"}], b"PNG", {})
    assert out == [{"type": "carrier-pigeon", "ok": False,
                    "detail": "unknown destination type"}]


def test_dispatch_routes_to_sender_and_shapes_result(monkeypatch):
    monkeypatch.setattr(_http, "post_multipart",
                        lambda *a, **k: (200, json.dumps({"ok": True})))
    ctx = {"creds": {"telegram_bot_token": "T"}, "subject": "s", "body": "b"}
    out = senders.dispatch([{"type": "telegram", "chat_id": "42"}], b"PNG", ctx)
    assert out[0]["ok"] is True
    assert out[0]["type"] == "telegram"
    assert out[0]["target"] == "42"


# --- telegram ---------------------------------------------------------------

def test_telegram_requires_token():
    ok, detail = telegram.send({"chat_id": "1"}, b"PNG", {"creds": {}})
    assert ok is False and "telegram_bot_token" in detail


def test_telegram_requires_chat_id():
    ok, detail = telegram.send({}, b"PNG", {"creds": {"telegram_bot_token": "T"}})
    assert ok is False and "chat_id" in detail


def test_telegram_success_posts_to_bot_api(monkeypatch):
    captured = {}

    def fake_post(url, fields=None, files=None, **kw):
        captured["url"] = url
        captured["fields"] = fields
        captured["files"] = files
        return 200, json.dumps({"ok": True})

    monkeypatch.setattr(_http, "post_multipart", fake_post)
    ok, detail = telegram.send(
        {"chat_id": " 42 "}, b"PNGBYTES",
        {"creds": {"telegram_bot_token": "SECRET"}, "subject": "Hi", "body": "there"})
    assert ok is True and detail == "sent"
    assert captured["url"] == "https://api.telegram.org/botSECRET/sendPhoto"
    assert captured["fields"]["chat_id"] == "42"  # stripped
    assert captured["files"]["photo"][1] == b"PNGBYTES"


def test_telegram_api_failure_surfaced(monkeypatch):
    monkeypatch.setattr(_http, "post_multipart",
                        lambda *a, **k: (200, json.dumps({"ok": False, "description": "bad"})))
    ok, detail = telegram.send({"chat_id": "1"}, b"P",
                               {"creds": {"telegram_bot_token": "T"}})
    assert ok is False and "telegram api" in detail


# --- webhook ----------------------------------------------------------------

def test_webhook_missing_url():
    ok, detail = webhook.send({}, b"P", {})
    assert ok is False and "url" in detail


def test_webhook_json_mode_base64_encodes_png(monkeypatch):
    captured = {}

    def fake_json(url, obj, **kw):
        captured["url"] = url
        captured["obj"] = obj
        return 200, "ok"

    monkeypatch.setattr(_http, "post_json", fake_json)
    ok, detail = webhook.send({"url": "https://x/y"}, b"PNG",
                              {"search_name": "S", "subject": "sub", "viz_type": "splunk.line"})
    assert ok is True and detail == "sent (200)"
    assert captured["url"] == "https://x/y"
    import base64
    assert captured["obj"]["image_png_b64"] == base64.b64encode(b"PNG").decode("ascii")


def test_webhook_multipart_mode(monkeypatch):
    called = {}
    monkeypatch.setattr(_http, "post_multipart",
                        lambda url, fields=None, files=None, **k: called.update(
                            url=url, files=files) or (201, "created"))
    ok, detail = webhook.send({"url": "https://x/y", "mode": "multipart"}, b"PNG", {})
    assert ok is True and "201" in detail
    assert called["files"]["image"][1] == b"PNG"


def test_webhook_non_2xx_is_failure(monkeypatch):
    monkeypatch.setattr(_http, "post_json", lambda *a, **k: (500, "boom"))
    ok, detail = webhook.send({"url": "https://x/y"}, b"P", {})
    assert ok is False and "http 500" in detail
