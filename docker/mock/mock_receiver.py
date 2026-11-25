"""
Mock delivery receiver for the alert action end-to-end tier. Stdlib only.

Listens on:
  :8080  plain HTTP   webhook deliveries (any POST under /hook/) and the control API
  :443   HTTPS        impersonates api.telegram.org and slack.com (the compose
                      file gives this container those names as network aliases
                      and CI makes Splunk trust the throwaway CA that signed the cert)
  :1025  SMTP         minimal sink: EHLO/HELO, MAIL, RCPT, DATA, RSET, NOOP, QUIT

Control API (host port 18080):
  GET    /_deliveries   every recorded request or message, bodies base64-encoded
  DELETE /_deliveries   forget everything

Nothing here interprets the payloads; the tests decode them independently.
"""
import base64
import json
import os
import socketserver
import ssl
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_LOCK = threading.Lock()
_RECORDS = []


def _record(**kw):
    kw["ts"] = time.time()
    with _LOCK:
        _RECORDS.append(kw)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("http %s %s\n" % (self.command, self.path.split("?")[0]))

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _handle(self):
        body = self._body()
        host = (self.headers.get("Host") or "").split(":")[0]
        path = self.path
        if path.startswith("/_deliveries"):
            if self.command == "DELETE":
                with _LOCK:
                    _RECORDS.clear()
                return self._send(200, {"ok": True})
            with _LOCK:
                return self._send(200, list(_RECORDS))
        _record(channel="http", host=host, method=self.command, path=path,
                headers={k.lower(): v for k, v in self.headers.items()},
                body_b64=base64.b64encode(body).decode())
        if host == "slack.com" and "files.getUploadURLExternal" in path:
            fid = "F" + uuid.uuid4().hex[:10].upper()
            return self._send(200, {"ok": True, "file_id": fid,
                                    "upload_url": "https://slack.com/upload/%s" % fid})
        if host == "slack.com" and path.startswith("/upload/"):
            return self._send(200, {"ok": True})
        if host == "slack.com" and "files.completeUploadExternal" in path:
            return self._send(200, {"ok": True, "files": [{"id": "F"}]})
        if host == "api.telegram.org" and path.endswith("/sendPhoto"):
            return self._send(200, {"ok": True, "result": {"message_id": 1}})
        return self._send(200, {"ok": True})

    do_GET = do_POST = do_PUT = do_DELETE = _handle


class SMTPHandler(socketserver.StreamRequestHandler):
    def _w(self, line):
        self.wfile.write((line + "\r\n").encode())
        self.wfile.flush()

    def handle(self):
        self._w("220 mock ESMTP")
        mail_from, rcpts = None, []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            cmd = line.decode("utf-8", "replace").rstrip("\r\n")
            verb = cmd.split(" ", 1)[0].upper()
            if verb == "EHLO":
                self._w("250-mock")
                self._w("250 8BITMIME")
            elif verb == "HELO":
                self._w("250 mock")
            elif verb == "MAIL":
                mail_from, rcpts = cmd.split(":", 1)[1].strip(), []
                self._w("250 OK")
            elif verb == "RCPT":
                rcpts.append(cmd.split(":", 1)[1].strip())
                self._w("250 OK")
            elif verb == "DATA":
                self._w("354 End data with <CR><LF>.<CR><LF>")
                buf = []
                while True:
                    ln = self.rfile.readline()
                    if not ln or ln in (b".\r\n", b".\n"):
                        break
                    if ln.startswith(b".."):
                        ln = ln[1:]
                    buf.append(ln)
                _record(channel="smtp", mail_from=mail_from, rcpts=rcpts,
                        body_b64=base64.b64encode(b"".join(buf)).decode())
                sys.stderr.write("smtp message for %s\n" % rcpts)
                self._w("250 OK queued")
            elif verb in ("RSET", "NOOP"):
                self._w("250 OK")
            elif verb == "QUIT":
                self._w("221 Bye")
                return
            else:
                self._w("502 not implemented")


class ThreadingTCP(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    threads = []
    plain = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    threads.append(threading.Thread(target=plain.serve_forever, daemon=True))
    cert = os.environ.get("MOCK_TLS_CERT", "/certs/server.pem")
    key = os.environ.get("MOCK_TLS_KEY", "/certs/server.key")
    if os.path.exists(cert) and os.path.exists(key):
        tls = ThreadingHTTPServer(("0.0.0.0", 443), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        tls.socket = ctx.wrap_socket(tls.socket, server_side=True)
        threads.append(threading.Thread(target=tls.serve_forever, daemon=True))
    else:
        sys.stderr.write("no TLS cert at %s: HTTPS impersonation disabled\n" % cert)
    smtp = ThreadingTCP(("0.0.0.0", 1025), SMTPHandler)
    threads.append(threading.Thread(target=smtp.serve_forever, daemon=True))
    for t in threads:
        t.start()
    sys.stderr.write("mock receiver up\n")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
