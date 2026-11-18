"""MYDAF 화면 (tkinter). 원클릭 시작/정지 + 설정."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from .config import Config, app_dir
from .remote import RemoteControl
from .runner import Runner

VERSION = "1.0.0"

# (설정키, 화면 이름, 종류)  종류: str | secret | int | bool | lines | choice:a,b
TABS = {
    "기본": [
        ("anthropic_api_key", "Claude API 키", "secret"),
        ("model", "AI 모델", "choice:claude-opus-5-5,claude-sonnet-5-5,claude-haiku-5-5"),
        ("naver_blog_id", "네이버 블로그 ID", "str"),
        ("publish_mode", "발행 방식 (draft=임시저장, publish=바로 발행)", "choice:draft,publish"),
        ("category", "카테고리 이름 (비우면 기본)", "str"),
        ("browser_channel", "사용할 브라우저", "choice:msedge,chrome"),
        ("daily_limit", "하루 최대 글 수 (최대 3, 넘길 수 없음)", "choice:1,2,3"),
        ("interval_min_minutes", "글 사이 최소 간격(분, 180 이상)", "int"),
        ("interval_max_minutes", "글 사이 최대 간격(분)", "int"),
        ("active_start_hour", "글 올리는 시작 시각(시)", "int"),
        ("active_end_hour", "글 올리는 종료 시각(시)", "int"),
    ],
    "키워드": [
        ("keywords", "키워드 (한 줄에 하나, 개수·길이 제한 없음)", "lines"),
        ("use_google_trends", "구글 트렌드에서 주제 자동 발굴", "bool"),
        ("topic_cooldown_days", "같은 주제 재사용 금지 기간(일)", "int"),
    ],
    "자료 출처": [
        ("naver_client_id", "네이버 검색 API Client ID (선택)", "str"),
        ("naver_client_secret", "네이버 검색 API Client Secret (선택)", "secret"),
        ("google_api_key", "Google 검색 API 키 (선택)", "secret"),
        ("google_cx", "Google 검색엔진 ID cx (선택)", "str"),
        ("rss_feeds", "RSS 주소 (한 줄에 하나)", "lines"),
        ("society_sources", "학회 RSS 또는 게시판 주소 (한 줄에 하나)", "lines"),
        ("use_kiss", "KISS 학술논문 검색 사용", "bool"),
        ("max_items_per_source", "출처별 최대 자료 수", "int"),
    ],
    "검증·출처표기": [
        ("min_independent_sources", "사실 1개당 필요한 서로 다른 매체 수", "int"),
        ("allow_single_source", "1곳만 확인된 사실도 사용", "bool"),
        ("min_verified_facts", "글을 쓰기 위한 최소 검증 사실 수", "int"),
        ("min_post_chars", "최소 본문 글자 수 (미달 시 올리지 않음)", "int"),
        ("citation_align", "출처 위치", "choice:right,left"),
        ("citation_font_size", "출처 글자 크기", "choice:11,13"),
    ],
    "원격 제어": [
        ("remote_enabled", "내 서버에서 원격 제어 허용", "bool"),
        ("remote_url", "서버 주소 (https://...)", "str"),
        ("remote_token", "접속 토큰", "secret"),
        ("remote_poll_seconds", "확인 주기(초)", "int"),
    ],
}


class App:
    def __init__(self):
        self.cfg = Config.load()
        self.msgs: queue.Queue[str] = queue.Queue()
        self.runner = Runner(self.cfg, self.msgs.put)
        self.remote = RemoteControl(self.cfg, self.runner, self.msgs.put)
        self.root = tk.Tk()
        self.root.title(f"MYDAF {VERSION} · 로컬 네이버 블로그 자동 포스팅")
        self.root.geometry("900x680")
        self.vars: dict[str, object] = {}
        self._build()
        self.remote.start()
        self.root.after(300, self._pump)

    # ------------------------------------------------------------ 화면 구성
    def _build(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        run = ttk.Frame(nb)
        nb.add(run, text="실행")
        bar = ttk.Frame(run)
        bar.pack(fill="x", pady=6)
        self.start_btn = ttk.Button(bar, text="▶ 원클릭 연속 실행", command=self.on_start)
        self.start_btn.pack(side="left", padx=4)
        ttk.Button(bar, text="■ 정지", command=self.on_stop).pack(side="left", padx=4)
        ttk.Button(bar, text="한 편만 실행", command=self.on_once).pack(side="left", padx=4)
        ttk.Button(bar, text="네이버 로그인", command=self.on_login).pack(side="left", padx=12)
        ttk.Button(bar, text="기록 폴더 열기", command=self.on_open_folder).pack(side="left", padx=4)
        self.status = tk.StringVar(value="대기 중")
        ttk.Label(run, textvariable=self.status).pack(anchor="w", padx=6)
        self.log = scrolledtext.ScrolledText(run, height=30, state="disabled", font=("Malgun Gothic", 10))
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

        for tab, items in TABS.items():
            frame = ttk.Frame(nb)
            nb.add(frame, text=tab)
            for row, (key, label, kind) in enumerate(items):
                ttk.Label(frame, text=label).grid(row=row, column=0, sticky="nw", padx=8, pady=5)
                self._field(frame, key, kind).grid(row=row, column=1, sticky="we", padx=8, pady=5)
            frame.columnconfigure(1, weight=1)
            ttk.Button(frame, text="저장", command=self.on_save).grid(row=len(items), column=1, sticky="e", padx=8, pady=10)

    def _field(self, parent, key, kind):
        value = getattr(self.cfg, key)
        if kind == "bool":
            v = tk.BooleanVar(value=value)
            self.vars[key] = v
            return ttk.Checkbutton(parent, variable=v)
        if kind == "lines":
            t = tk.Text(parent, height=8, width=60)
            t.insert("1.0", "\n".join(value))
            self.vars[key] = t
            return t
        v = tk.StringVar(value=str(value))
        self.vars[key] = v
        if kind.startswith("choice:"):
            return ttk.Combobox(parent, textvariable=v, values=kind[7:].split(","))
        return ttk.Entry(parent, textvariable=v, show="•" if kind == "secret" else "")

    # ------------------------------------------------------------ 동작
    def _collect(self) -> dict:
        out = {}
        for key, w in self.vars.items():
            out[key] = w.get("1.0", "end") if isinstance(w, tk.Text) else w.get()
        return out

    def on_save(self, quiet=False):
        try:
            self.cfg.update(self._collect())
            self.cfg.remote_token = self.vars["remote_token"].get()
            self.cfg.save()
        except ValueError as e:
            messagebox.showerror("저장 실패", f"숫자 칸을 확인하세요: {e}")
            return False
        self.remote.stop()
        self.remote = RemoteControl(self.cfg, self.runner, self.msgs.put)
        self.remote.start()
        for key in ("daily_limit", "interval_min_minutes", "interval_max_minutes",
                    "active_start_hour", "active_end_hour"):
            self.vars[key].set(str(getattr(self.cfg, key)))   # 안전장치로 조정된 값을 화면에 반영
        if not quiet:
            self.msgs.put("설정을 저장했습니다.")
        return True

    def _ready(self) -> bool:
        if not self.on_save(quiet=True):
            return False
        missing = [n for k, n in (("anthropic_api_key", "Claude API 키"), ("naver_blog_id", "네이버 블로그 ID"))
                   if not getattr(self.cfg, k)]
        if missing:
            messagebox.showwarning("설정 필요", ", ".join(missing) + " 을(를) 입력하세요.")
            return False
        return True

    def on_start(self):
        if self._ready():
            self.runner.start()

    def on_stop(self):
        self.runner.stop()
        self.msgs.put("정지 요청: 지금 하던 글까지만 마치고 멈춥니다.")

    def on_once(self):
        if self._ready() and not self.runner.running:
            threading.Thread(target=self.runner.run_once, daemon=True).start()

    def on_login(self):
        def job():
            from .naver import NaverBlog
            self.msgs.put("브라우저에서 네이버에 로그인하세요 (최대 5분 대기).")
            with NaverBlog(self.cfg.naver_blog_id, self.cfg.browser_channel) as nb:
                ok = nb.is_logged_in() or nb.login_interactive()
            self.msgs.put("네이버 로그인 확인됨." if ok else "로그인 확인 실패.")
        self.on_save(quiet=True)
        threading.Thread(target=job, daemon=True).start()

    def on_open_folder(self):
        path = str(app_dir())
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", path])

    def _pump(self):
        while not self.msgs.empty():
            line = self.msgs.get()
            self.log.configure(state="normal")
            self.log.insert("end", line + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        st = self.runner.status()
        names = {"idle": "대기 중", "running": "작업 중", "waiting": "다음 글 대기", "stopping": "정지 중"}
        self.status.set(f"상태: {names.get(st['state'], st['state'])} · 오늘 {st['today']}/{st['daily_limit']}"
                        f"{' · 원격 제어 켜짐' if self.cfg.remote_enabled else ''}")
        self.root.after(500, self._pump)

    def run(self):
        self.root.mainloop()


def main():
    App().run()
