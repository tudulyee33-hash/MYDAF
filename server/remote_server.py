"""MYDAF 원격 제어 서버 (내 서버용, 파이썬 표준 라이브러리만 사용).

실행:  MYDAF_TOKEN=아무도모르는긴문자열 python remote_server.py --port 8787
브라우저: http://서버주소:8787/?token=같은토큰   → 상태 확인, 시작/정지/한 편 실행/설정 변경
인터넷에 공개할 때는 반드시 HTTPS(nginx, Caddy 등) 뒤에 두세요.
"""
from __future__ import annotations

import argparse
import hmac
import html
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = os.environ.get("MYDAF_TOKEN", "")
LOCK = threading.Lock()
QUEUE: dict[str, list[dict]] = {}       # device -> 대기 명령
DEVICES: dict[str, dict] = {}           # device -> 마지막 보고


def authorized(handler, query) -> bool:
    got = handler.headers.get("Authorization", "").removeprefix("Bearer ").strip() or query.get("token", [""])[0]
    return bool(TOKEN) and hmac.compare_digest(got, TOKEN)


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>MYDAF 원격 제어</title><body style="font-family:sans-serif;max-width:760px;margin:24px auto;padding:0 16px">
<h2>MYDAF 원격 제어</h2>{rows}
<p style="color:#888">10초마다 새로고침</p><script>setTimeout(()=>location.reload(),10000)</script></body>"""

ROW = """<div style="border:1px solid #ccc;border-radius:8px;padding:12px;margin:12px 0">
<b>{dev}</b> · 마지막 연락 {ago}초 전<pre style="white-space:pre-wrap">{status}</pre>
<form method=post action="/api/send?token={token}">
<input type=hidden name=device value="{dev}">
<button name=type value=start>▶ 시작</button> <button name=type value=stop>■ 정지</button>
<input name=topic placeholder="주제(선택)"> <button name=type value=run_once>한 편 실행</button><br><br>
<textarea name=values rows=3 style="width:100%" placeholder='설정 변경 JSON 예: {{"daily_limit": 3, "publish_mode": "draft"}}'></textarea>
<button name=type value=set_config>설정 변경</button></form></div>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not authorized(self, q):
            return self._send(401, '{"error":"unauthorized"}')
        if u.path == "/api/commands":
            dev = q.get("device", [""])[0]
            with LOCK:
                cmds, QUEUE[dev] = QUEUE.get(dev, []), []
            return self._send(200, json.dumps({"commands": cmds}, ensure_ascii=False))
        if u.path == "/":
            with LOCK:
                rows = "".join(ROW.format(dev=html.escape(d), ago=int(time.time() - v["at"]),
                                          status=html.escape(json.dumps(v["report"], ensure_ascii=False, indent=1)),
                                          token=html.escape(q["token"][0]) if "token" in q else "")
                               for d, v in DEVICES.items()) or "<p>아직 연결된 PC가 없습니다.</p>"
            return self._send(200, PAGE.format(rows=rows), "text/html; charset=utf-8")
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not authorized(self, q):
            return self._send(401, '{"error":"unauthorized"}')
        if u.path == "/api/report":
            rep = json.loads(self._body() or b"{}")
            with LOCK:
                DEVICES[rep.get("device", "?")] = {"at": time.time(), "report": rep}
            return self._send(200, '{"ok":true}')
        if u.path == "/api/send":
            raw = self._body().decode("utf-8")
            if self.headers.get("Content-Type", "").startswith("application/json"):
                form = json.loads(raw)
            else:
                form = {k: v[0] for k, v in parse_qs(raw).items()}
            cmd = {"id": uuid.uuid4().hex[:10], "type": form.get("type")}
            if form.get("topic"):
                cmd["topic"] = form["topic"]
            if form.get("values"):
                cmd["values"] = form["values"] if isinstance(form["values"], dict) else json.loads(form["values"])
            with LOCK:
                QUEUE.setdefault(form.get("device", ""), []).append(cmd)
            if "json" in self.headers.get("Content-Type", ""):
                return self._send(200, json.dumps(cmd))
            self.send_response(303)
            self.send_header("Location", "/?token=" + q.get("token", [""])[0])
            self.end_headers()
            return
        self._send(404, '{"error":"not found"}')

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    if len(TOKEN) < 16:
        raise SystemExit("MYDAF_TOKEN 환경변수에 16자 이상 토큰을 넣으세요.")
    print(f"MYDAF 원격 제어 서버: http://{args.host}:{args.port}/?token=...")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
