"""(선택) 내 서버에서 원격 제어. 기본은 꺼져 있다.

프로그램이 내 서버에 주기적으로 '할 일'을 물어보는 방식이라 PC에 포트를 열 필요가 없다.
서버가 줄 수 있는 명령: start, stop, run_once(topic), set_config(values), status
업데이트·파일 실행 같은 명령은 일부러 만들지 않았다.

서버 규격 (server/remote_server.py 가 이 규격을 구현함):
  GET  {url}/api/commands?device=ID      → {"commands": [{"id": "...", "type": "...", ...}]}
  POST {url}/api/report                   ← {"device": ID, "command_id": ..., "ok": bool, "status": {...}}
  인증: Authorization: Bearer <토큰>
"""
from __future__ import annotations

import platform
import threading
import uuid

import requests

from .config import Config, app_dir
from .logs import log

ALLOWED = {"start", "stop", "run_once", "set_config", "status"}


def device_id() -> str:
    p = app_dir() / "device_id"
    if not p.exists():
        p.write_text(f"{platform.node()}-{uuid.uuid4().hex[:8]}", encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


class RemoteControl:
    def __init__(self, cfg: Config, runner, say=print):
        self.cfg, self.runner, self.say = cfg, runner, say
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self):
        if not (self.cfg.remote_enabled and self.cfg.remote_url and self.cfg.remote_token):
            return
        if self.thread and self.thread.is_alive():
            return
        self._stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self.say(f"원격 제어 연결: {self.cfg.remote_url}")

    def stop(self):
        self._stop.set()

    def _headers(self):
        return {"Authorization": f"Bearer {self.cfg.remote_token}"}

    def _loop(self):
        dev = device_id()
        base = self.cfg.remote_url.rstrip("/")
        while not self._stop.is_set():
            try:
                r = requests.get(f"{base}/api/commands", params={"device": dev}, headers=self._headers(), timeout=15)
                r.raise_for_status()
                for cmd in r.json().get("commands", []):
                    self._report(base, dev, cmd.get("id"), *self.handle(cmd))
                if not r.json().get("commands"):
                    self._report(base, dev, None, True, "heartbeat")
            except Exception as e:
                log.warning("원격 제어 통신 실패: %s", e)
            self._stop.wait(max(10, self.cfg.remote_poll_seconds))

    def handle(self, cmd: dict) -> tuple[bool, str]:
        kind = cmd.get("type")
        if kind not in ALLOWED:
            return False, f"허용되지 않은 명령: {kind}"
        self.say(f"원격 명령: {kind}")
        if kind == "start":
            self.runner.start()
        elif kind == "stop":
            self.runner.stop()
        elif kind == "run_once":
            if self.runner.running:
                return False, "연속 실행 중에는 단건 실행 불가"
            threading.Thread(target=self.runner.run_once, args=(cmd.get("topic") or None,), daemon=True).start()
        elif kind == "set_config":
            changed = self.cfg.update(cmd.get("values", {}))
            self.cfg.save()
            return True, "변경: " + ", ".join(changed)
        return True, kind

    def _report(self, base, dev, command_id, ok, message):
        try:
            requests.post(f"{base}/api/report", headers=self._headers(), timeout=15, json={
                "device": dev, "command_id": command_id, "ok": ok, "message": message,
                "status": self.runner.status()})
        except Exception as e:
            log.warning("원격 보고 실패: %s", e)
