"""Unit tests for the dependency-free multipart/JSON HTTP helpers."""
from senders import _http


def test_encode_multipart_has_boundary_and_parts():
    ctype, body = _http.encode_multipart(
        fields={"caption": "hello"},
        files={"photo": ("viz.png", b"\x89PNG", "image/png")},
    )
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=", 1)[1]
    # boundary must actually appear in the body, opening and closing it
    assert boundary.encode() in body
    assert body.rstrip(b"\r\n").endswith(b"--" + boundary.encode() + b"--")


def test_encode_multipart_serialises_field_and_file():
    _ctype, body = _http.encode_multipart(
        fields={"chat_id": "12345"},
        files={"photo": ("viz.png", b"PNGDATA", "image/png")},
    )
    assert b'name="chat_id"' in body
    assert b"12345" in body
    assert b'filename="viz.png"' in body
    assert b"Content-Type: image/png" in body
    assert b"PNGDATA" in body


def test_encode_multipart_empty_is_just_closing_boundary():
    ctype, body = _http.encode_multipart()
    boundary = ctype.split("boundary=", 1)[1]
    assert body.rstrip(b"\r\n") == b"--" + boundary.encode() + b"--"
