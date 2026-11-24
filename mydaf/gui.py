"""MYDAF 화면 (tkinter). 사이드바 + 카드형 홈, 오른쪽 아래 원클릭 자동 등록, 최초 1회 설정 마법사."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox

from . import install
from .config import HARD_DAILY_MAX, MIN_INTERVAL_FLOOR, Config, app_dir
from .logs import POST_DIR, read_history
from .remote import RemoteControl
from .runner import COUNTED, Runner, display_pct

VERSION = "1.6.1"

# ------------------------------------------------------------------ 디자인
C = {
    "bg": "#F5F7FB", "side": "#FFFFFF", "card": "#FFFFFF", "line": "#E5E7EB",
    "text": "#111827", "muted": "#6B7280", "faint": "#9CA3AF",
    "primary": "#2563EB", "primary_dk": "#1D4ED8", "primary_bg": "#EFF6FF",
    "ok": "#10B981", "ok_bg": "#ECFDF5", "warn": "#D97706", "warn_bg": "#FFFBEB",
    "bad": "#DC2626", "bad_bg": "#FEF2F2", "hover": "#F3F4F6", "sel": "#EEF2FF",
}
FONT = "Malgun Gothic" if sys.platform == "win32" else "NanumGothic"


def F(size=10, weight="normal"):
    return (FONT, size, weight)


STATUS_CHIP = {
    "published": ("발행", C["ok"], C["ok_bg"]), "draft": ("임시저장", C["primary_dk"], C["primary_bg"]),
    "skipped": ("건너뜀", C["muted"], C["hover"]), "blocked": ("보류", C["warn"], C["warn_bg"]),
    "error": ("오류", C["bad"], C["bad_bg"]), "naver_error": ("오류", C["bad"], C["bad_bg"]),
    "unknown": ("확인 필요", C["warn"], C["warn_bg"]), "draft_failed": ("저장 실패", C["bad"], C["bad_bg"]),
}

# (설정키, 화면 이름, 종류, 도움말)  종류: str | secret | int | bool | lines | choice:a,b
PAGES = {
    "keywords": ("키워드", [
        ("keywords", "키워드", "lines", "한 줄에 하나씩 (쉼표로 구분해도 돼요). 개수·길이 제한 없음"),
        ("use_google_trends", "구글 트렌드에서 주제 자동 발굴", "bool", "오늘 뜨는 검색어 중 내 키워드와 관련된 것을 우선"),
        ("topic_cooldown_days", "같은 주제 재사용 금지(일)", "int", "최근에 쓴 주제는 이 기간 동안 다시 쓰지 않음"),
    ]),
    "writing": ("글쓰기 설정", [
        ("writer_style", "작가 스타일", "choice:정보 전달형 전문가,트렌드 관찰형,친근한 이웃형,분석 리포트형", "글의 말투와 구성"),
        ("heading_style", "소제목 모양", "choice:quote,bold", "quote = 인용구 박스, bold = 굵은 글씨"),
        ("heading_font_size", "소제목 글자 크기", "choice:19,24,28,30,34,38", "기본 34"),
        ("body_font_size", "본문 글자 크기", "choice:15,16,19,24,28,30", "기본 30"),
        ("use_images", "이미지 자동 준비", "bool", "소제목마다 자유 라이선스 사진을 찾아 넣고 출처에 표기"),
        ("images_per_post", "글 하나당 최대 이미지 수", "int", ""),
        ("pexels_api_key", "Pexels API 키", "secret", "선택 · pexels.com 무료 발급, 없으면 위키미디어 공용 사용"),
        ("show_browser", "작성 중 블로그 화면 보이기", "bool", "끄면 화면 없이 뒤에서 작성"),
    ]),
    "sources": ("자료 출처", [
        ("rss_feeds", "RSS 주소", "lines", "한 줄에 하나"),
        ("society_sources", "학회 RSS · 게시판 주소", "lines", "한 줄에 하나"),
        ("use_kiss", "KISS 학술논문 검색", "bool", "논문 초록과 서지 정보만 인용"),
        ("naver_client_id", "네이버 검색 API Client ID", "str", "선택 · developers.naver.com 무료 발급"),
        ("naver_client_secret", "네이버 검색 API Secret", "secret", "선택"),
        ("google_api_key", "Google 검색 API 키", "secret", "선택 · 없으면 구글 뉴스만 사용"),
        ("google_cx", "Google 검색엔진 ID (cx)", "str", "선택"),
        ("max_items_per_source", "출처별 최대 자료 수", "int", ""),
    ]),
    "quality": ("검증 · 출처 표기", [
        ("min_independent_sources", "사실 1개당 필요한 매체 수", "int", "서로 다른 매체에서 확인돼야 사용"),
        ("allow_single_source", "1곳만 확인된 사실도 사용", "bool", "끄는 것을 권장"),
        ("min_verified_facts", "최소 검증 사실 수", "int", "미달이면 그 주제는 쓰지 않음"),
        ("min_post_chars", "최소 본문 글자 수", "int", "미달이면 올리지 않음"),
        ("citation_align", "출처 위치", "choice:right,left", "글 맨 아래 작은 글씨"),
        ("citation_font_size", "출처 글자 크기", "choice:11,13", ""),
    ]),
    "publish": ("발행 설정", [
        ("ai_provider", "글 쓸 AI", "choice:gemini,claude", "gemini = 무료 키 가능, claude = 유료·최고품질"),
        ("gemini_api_key", "Gemini API 키", "secret", "aistudio.google.com 에서 무료 발급"),
        ("gemini_model", "Gemini 모델", "combo:gemini-3.5-flash,gemini-3.5-flash-lite,gemini-flash-lite-latest",
         "무료는 flash 권장 · 새 모델 이름을 직접 입력해도 됨"),
        ("anthropic_api_key", "Claude API 키", "secret", "console.anthropic.com 에서 발급"),
        ("model", "Claude 모델", "choice:claude-opus-5-5,claude-sonnet-5-5", "Opus 가 가장 고품질"),
        ("naver_blog_id", "네이버 블로그 ID", "str", "blog.naver.com/ 뒤의 아이디"),
        ("publish_mode", "발행 방식", "choice:draft,publish", "draft = 임시저장, publish = 바로 발행"),
        ("category", "카테고리", "str", "비우면 기본 카테고리"),
        ("browser_channel", "사용할 브라우저", "choice:msedge,chrome", ""),
        ("daily_limit", f"하루 최대 글 수", "choice:1,2,3", f"최대 {HARD_DAILY_MAX}개 고정"),
        ("interval_min_minutes", "글 사이 최소 간격(분)", "int", f"{MIN_INTERVAL_FLOOR}분 이상"),
        ("interval_max_minutes", "글 사이 최대 간격(분)", "int", ""),
        ("active_start_hour", "올리는 시작 시각(시)", "int", ""),
        ("active_end_hour", "올리는 종료 시각(시)", "int", ""),
        ("auto_start", "프로그램을 켜면 자동 등록 바로 시작", "bool", ""),
    ]),
    "remote": ("원격 제어", [
        ("remote_enabled", "내 서버에서 원격 제어 허용", "bool", "기본 꺼짐 · 업데이트 명령은 없음"),
        ("remote_url", "서버 주소", "str", "https://..."),
        ("remote_token", "접속 토큰", "secret", "서버와 같은 값"),
        ("remote_poll_seconds", "확인 주기(초)", "int", ""),
    ]),
}

NAV = [
    (None, [("home", "홈", "⌂"), ("history", "작업 기록", "☰")]),
    ("자동 등록 설정", [("keywords", "키워드", "#"), ("writing", "글쓰기 설정", "¶"), ("sources", "자료 출처", "◎"),
                   ("quality", "검증 · 출처 표기", "✓"), ("publish", "발행 설정", "✎")]),
    ("연결", [("remote", "원격 제어", "⇄")]),
]


# ------------------------------------------------------------------ 작은 부품
class Btn(tk.Label):
    """평평한 버튼 (Windows/리눅스에서 같은 모양)."""

    def __init__(self, parent, text, command, kind="primary", size=10, padx=16, pady=8, **kw):
        styles = {
            "primary": (C["primary"], "white", C["primary_dk"]),
            "soft": (C["primary_bg"], C["primary_dk"], "#DBEAFE"),
            "ghost": (C["card"], C["primary_dk"], C["hover"]),
            "danger": (C["bad_bg"], C["bad"], "#FEE2E2"),
        }
        self.bg, fg, self.hover = styles[kind]
        super().__init__(parent, text=text, bg=self.bg, fg=fg, font=F(size, "bold"),
                         padx=padx, pady=pady, cursor="hand2", **kw)
        self.command = command
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self.configure(bg=self.hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self.bg))

    def restyle(self, text, kind):
        styles = {"primary": (C["primary"], "white", C["primary_dk"]), "danger": (C["bad_bg"], C["bad"], "#FEE2E2")}
        self.bg, fg, self.hover = styles[kind]
        self.configure(text=text, bg=self.bg, fg=fg)


def card(parent, title=None, link=None, link_cmd=None):
    outer = tk.Frame(parent, bg=C["card"], highlightthickness=1, highlightbackground=C["line"])
    if title:
        head = tk.Frame(outer, bg=C["card"])
        head.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(head, text=title, bg=C["card"], fg=C["text"], font=F(12, "bold")).pack(side="left")
        if link:
            lab = tk.Label(head, text=link, bg=C["card"], fg=C["primary_dk"], font=F(9), cursor="hand2")
            lab.pack(side="right")
            lab.bind("<Button-1>", lambda e: link_cmd())
    return outer


def chip(parent, text, fg, bg):
    return tk.Label(parent, text=text, fg=fg, bg=bg, font=F(9, "bold"), padx=8, pady=2)


def autowrap(label):
    """라벨 폭에 맞춰 자동 줄바꿈."""
    label.bind("<Configure>", lambda e: label.configure(wraplength=max(e.width - 4, 50)))
    return label


def draw_donut(cv: tk.Canvas, pct: int, size: int, caption: str = ""):
    """원형(도넛) 진행률 그래프. 가운데 큰 % 숫자."""
    cv.delete("all")
    pad, width = 10, 14
    box = (pad, pad, size - pad, size - pad)
    cv.create_oval(*box, outline=C["line"], width=width)
    if pct >= 100:
        cv.create_oval(*box, outline=C["primary"], width=width)
    elif pct > 0:
        cv.create_arc(*box, start=90, extent=-3.6 * pct, style="arc", outline=C["primary"], width=width)
    cv.create_text(size / 2, size / 2 - (8 if caption else 0), text=f"{pct}%", fill=C["text"], font=F(22, "bold"))
    if caption:
        cv.create_text(size / 2, size / 2 + 22, text=caption, fill=C["muted"], font=F(8))


def draw_bar(cv: tk.Canvas, pct: int, height: int):
    """두꺼운 진행 막대. 막대 안에 % 표시."""
    cv.delete("all")
    w = max(cv.winfo_width(), 50)
    r = height / 2
    def pill(x1, color):
        if x1 - 0 < height:
            cv.create_oval(0, 0, height, height, fill=color, outline=color)
            return
        cv.create_oval(0, 0, height, height, fill=color, outline=color)
        cv.create_oval(x1 - height, 0, x1, height, fill=color, outline=color)
        cv.create_rectangle(r, 0, x1 - r, height, fill=color, outline=color)
    pill(w, C["line"])
    if pct > 0:
        pill(max(w * pct / 100, height), C["primary"])
    fill_end = w * pct / 100
    inside = fill_end > 60
    cv.create_text(fill_end - 10 if inside else fill_end + 10, r, text=f"{pct}%",
                   anchor="e" if inside else "w", fill="white" if inside else C["primary_dk"], font=F(10, "bold"))


def hline(parent):
    tk.Frame(parent, bg=C["line"], height=1).pack(fill="x")


class ScrollPage(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=C["bg"])
        self.canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        bar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=C["bg"])
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))


# ------------------------------------------------------------------ 앱
class App:
    def __init__(self):
        self.cfg = Config.load()
        self.msgs: queue.Queue[str] = queue.Queue()
        self.log_lines: list[str] = []
        self.runner = Runner(self.cfg, self.msgs.put)
        self.remote = RemoteControl(self.cfg, self.runner, self.msgs.put)
        self.vars: dict[str, object] = {}
        self.login_state = "확인 전"

        self.root = tk.Tk()
        self.root.title("MYDAF")
        self.root.geometry("1240x800")
        self.root.minsize(1080, 700)
        self.root.configure(bg=C["bg"])
        self._set_icon()

        self.side = tk.Frame(self.root, bg=C["side"], width=232, highlightthickness=1,
                             highlightbackground=C["line"])
        self.side.pack(side="left", fill="y")
        self.side.pack_propagate(False)
        self.main = tk.Frame(self.root, bg=C["bg"])
        self.main.pack(side="left", fill="both", expand=True)

        self.nav_items: dict[str, tuple[tk.Frame, list[tk.Label]]] = {}
        self._build_sidebar()
        self.current = None
        if self.cfg.setup_done and self.cfg.ai_key():
            self.show("home")
        else:
            self.show_setup()

        self.remote.start()
        self.root.after(400, self._startup_install)
        self.root.after(1200, self._startup_login_check)
        if self.cfg.auto_start and self.cfg.setup_done:
            self.root.after(1500, self.on_toggle)
        self.root.after(300, self._pump)

    # ------------------------------------------------------------ 공통
    def _set_icon(self):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        try:
            if sys.platform == "win32" and (base / "assets/mydaf.ico").exists():
                self.root.iconbitmap(default=str(base / "assets/mydaf.ico"))
            elif (base / "assets/mydaf.png").exists():
                self._icon_img = tk.PhotoImage(file=str(base / "assets/mydaf.png")).subsample(16)
                self.root.iconphoto(True, self._icon_img)
        except tk.TclError:
            pass

    def _logo(self, parent, bg):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        try:
            self._logo_img = tk.PhotoImage(file=str(base / "assets/mydaf.png")).subsample(24)
            return tk.Label(parent, image=self._logo_img, bg=bg)
        except tk.TclError:
            return tk.Label(parent, text="M", bg=C["primary"], fg="white", font=F(14, "bold"), width=3)

    def _startup_login_check(self):
        """켤 때 저장된 네이버 로그인이 살아 있는지 확인. 쿠키 파일만 읽어 즉시 끝내고,
        판단이 안 될 때만 화면 없는 브라우저로 확인한다 (켤 때 메모리·시간 절약)."""
        from .logincheck import quick_login_state

        def job():
            state = quick_login_state()
            if state is not None:
                self.login_state = "됨" if state else "필요"
                return
            if self.runner.running:
                return
            try:
                from .naver import NaverBlog
                with NaverBlog(self.cfg.naver_blog_id, self.cfg.browser_channel, headless=True) as nb:
                    ok = nb.is_logged_in()
                self.login_state = "됨" if ok else "필요"
            except Exception as e:
                self.msgs.put(f"네이버 로그인 자동 확인 실패: {e.__class__.__name__}")
        threading.Thread(target=job, daemon=True).start()

    def _startup_install(self):
        threading.Thread(target=install.startup_check, args=(app_dir(),), daemon=True).start()

    def clear_main(self):
        for w in self.main.winfo_children():
            w.destroy()
        self.vars.clear()

    def header(self, title, right_widgets=True):
        bar = tk.Frame(self.main, bg=C["card"], height=72, highlightthickness=1, highlightbackground=C["line"])
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text=title, bg=C["card"], fg=C["text"], font=F(16, "bold")).pack(side="left", padx=28)
        if right_widgets:
            self.head_btn = Btn(bar, "✎ 한 편 바로 쓰기", self.on_head_button, padx=18, pady=9)
            self.head_btn.pack(side="right", padx=(8, 24))
            self.view_btn = Btn(bar, "", self.on_toggle_view, kind="soft", size=9, padx=14, pady=8)
            self.view_btn.pack(side="right", padx=4)
            self.login_pill = tk.Label(bar, bg=C["hover"], font=F(9, "bold"), padx=12, pady=6)
            self.login_pill.pack(side="right", padx=8)
            self.login_pill.bind("<Button-1>", lambda e: self.on_login())
            self._refresh_header()
        return bar

    def _refresh_header(self):
        if not getattr(self, "login_pill", None) or not self.login_pill.winfo_exists():
            return
        ok = self.login_state == "됨"
        self.login_pill.configure(text=("● 네이버 로그인됨" if ok else f"● 네이버 로그인 {self.login_state}"),
                                  fg=C["ok"] if ok else C["muted"], bg=C["ok_bg"] if ok else C["hover"])
        self.view_btn.configure(text=("▣ 블로그 화면 보기 켜짐" if self.cfg.show_browser else "▢ 블로그 화면 숨김"))
        if self.runner.running or (self.runner.job and not self.runner.job.get("done")):
            self.head_btn.restyle("멈추기", "danger")
        else:
            self.head_btn.restyle("✎ 한 편 바로 쓰기", "primary")

    def on_head_button(self):
        if self.runner.running:
            self.on_toggle()
        elif not (self.runner.job and not self.runner.job.get("done")):
            self.on_new_post()

    def on_toggle_view(self):
        self.cfg.show_browser = not self.cfg.show_browser
        self.cfg.save()
        self.msgs.put("작성 중 블로그 화면을 " + ("보여줘요." if self.cfg.show_browser else "숨겨요 (뒤에서 작성)."))
        self._refresh_header()

    # ------------------------------------------------------------ 사이드바
    def _build_sidebar(self):
        top = tk.Frame(self.side, bg=C["side"])
        top.pack(fill="x", padx=18, pady=(20, 14))
        self._logo(top, C["side"]).pack(side="left")
        txt = tk.Frame(top, bg=C["side"])
        txt.pack(side="left", padx=10)
        tk.Label(txt, text="MYDAF", bg=C["side"], fg=C["text"], font=F(13, "bold")).pack(anchor="w")
        tk.Label(txt, text=f"블로그 자동 등록 {VERSION}", bg=C["side"], fg=C["muted"], font=F(9)).pack(anchor="w")

        for section, items in NAV:
            if section:
                tk.Frame(self.side, bg=C["line"], height=1).pack(fill="x", padx=14, pady=(10, 0))
                tk.Label(self.side, text=section, bg=C["side"], fg=C["faint"], font=F(9)).pack(
                    anchor="w", padx=22, pady=(10, 4))
            for key, label, icon in items:
                row = tk.Frame(self.side, bg=C["side"], cursor="hand2")
                row.pack(fill="x", padx=10, pady=1)
                a = tk.Label(row, text=icon, bg=C["side"], fg=C["muted"], font=F(11), width=2)
                a.pack(side="left", padx=(10, 6), pady=8)
                b = tk.Label(row, text=label, bg=C["side"], fg=C["text"], font=F(10))
                b.pack(side="left")
                for w in (row, a, b):
                    w.bind("<Button-1>", lambda e, k=key: self.show(k))
                self.nav_items[key] = (row, [a, b])

        bottom = tk.Frame(self.side, bg=C["side"])
        bottom.pack(side="bottom", fill="x", padx=12, pady=14)
        self.job_box = tk.Frame(bottom, bg=C["card"], highlightthickness=1, highlightbackground=C["line"])
        jh = tk.Frame(self.job_box, bg=C["card"])
        jh.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(jh, text="● 지금 하는 작업", bg=C["card"], fg=C["primary_dk"], font=F(9, "bold")).pack(side="left")
        self.job_pct = tk.Label(jh, bg=C["card"], fg=C["primary_dk"], font=F(9, "bold"))
        self.job_pct.pack(side="right")
        self.job_sub = tk.Label(self.job_box, bg=C["card"], fg=C["muted"], font=F(8), anchor="w")
        self.job_sub.pack(fill="x", padx=12, pady=(2, 4))
        self.job_bar = tk.Canvas(self.job_box, height=4, bg=C["line"], highlightthickness=0)
        self.job_bar.pack(fill="x", padx=12, pady=(0, 10))
        self.remote_box = tk.Frame(bottom, bg=C["card"], highlightthickness=1, highlightbackground=C["line"])
        self.remote_box.pack(fill="x")
        self.remote_lab = tk.Label(self.remote_box, bg=C["card"], fg=C["text"], font=F(9, "bold"), anchor="w")
        self.remote_lab.pack(fill="x", padx=12, pady=(10, 0))
        self.remote_sub = tk.Label(self.remote_box, bg=C["card"], fg=C["muted"], font=F(8), anchor="w")
        self.remote_sub.pack(fill="x", padx=12, pady=(0, 10))
        prof = tk.Frame(bottom, bg=C["side"])
        prof.pack(fill="x", pady=(12, 0))
        tk.Label(prof, text=(self.cfg.naver_blog_id or "?")[:1].upper(), bg=C["primary_bg"], fg=C["primary_dk"],
                 font=F(10, "bold"), width=3, pady=4).pack(side="left")
        info = tk.Frame(prof, bg=C["side"])
        info.pack(side="left", padx=8)
        self.prof_name = tk.Label(info, bg=C["side"], fg=C["text"], font=F(9, "bold"), anchor="w")
        self.prof_name.pack(anchor="w")
        self.prof_sub = tk.Label(info, bg=C["side"], fg=C["muted"], font=F(8), anchor="w")
        self.prof_sub.pack(anchor="w")
        gear = tk.Label(prof, text="⚙", bg=C["side"], fg=C["muted"], font=F(13), cursor="hand2")
        gear.pack(side="right")
        gear.bind("<Button-1>", lambda e: self.show("publish"))
        self._refresh_side()

    def _refresh_job_box(self):
        job = self.runner.job
        active = job and not job.get("done")
        if active:
            if not self.job_box.winfo_ismapped():
                self.job_box.pack(fill="x", pady=(0, 10), before=self.remote_box)
            from .runner import STEPS
            pct = display_pct(job)
            self.job_pct.configure(text=f"{pct}%")
            self.root.title(f"MYDAF · 작성 중 {pct}%")
            self.job_sub.configure(text=f"{job['topic'][:14]} · {STEPS[job['step']]}")
            w = max(self.job_bar.winfo_width(), 1)
            self.job_bar.delete("all")
            self.job_bar.create_rectangle(0, 0, w * pct / 100, 4, fill=C["primary"], width=0)
        elif self.job_box.winfo_ismapped():
            self.job_box.pack_forget()
            self.root.title("MYDAF")

    def _refresh_side(self):
        on = self.cfg.remote_enabled and self.cfg.remote_url
        self.remote_lab.configure(text=("● 원격 제어 켜짐" if on else "● 원격 제어 꺼짐"),
                                  fg=C["ok"] if on else C["faint"])
        self.remote_sub.configure(text=(self.cfg.remote_url[:30] if on else "필요할 때 '원격 제어'에서 켜요"))
        self.prof_name.configure(text=self.cfg.naver_blog_id or "블로그 미설정")
        self.prof_sub.configure(text=f"네이버 로그인 {self.login_state}")

    def _select_nav(self, key):
        for k, (row, labels) in self.nav_items.items():
            bg = C["sel"] if k == key else C["side"]
            row.configure(bg=bg)
            for lab in labels:
                lab.configure(bg=bg)
            labels[1].configure(font=F(10, "bold") if k == key else F(10),
                                fg=C["primary_dk"] if k == key else C["text"])

    def show(self, key):
        self.current = key
        self.clear_main()
        self._select_nav(key)
        if key == "home":
            self.page_home()
        elif key == "history":
            self.page_history()
        else:
            self.page_form(key)

    # ------------------------------------------------------------ 홈
    def page_home(self):
        self.header("홈")
        page = ScrollPage(self.main)
        page.pack(fill="both", expand=True)
        self.home_scroll = page
        body = tk.Frame(page.inner, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=28, pady=24)
        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="right", fill="y", padx=(20, 0))
        tk.Frame(right, bg=C["bg"], width=330, height=1).pack()
        left = tk.Frame(body, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True)

        # 진행 상황
        prog = card(left, "진행 상황", "전체 기록 보기", lambda: self.show("history"))
        prog.pack(fill="x")
        stats = tk.Frame(prog, bg=C["card"])
        stats.pack(fill="x", padx=20, pady=(4, 12))
        self.stat_vals = {}
        for key, label in (("state", "상태"), ("today", "오늘 등록"), ("next", "다음 등록 가능"), ("kw", "키워드")):
            box = tk.Frame(stats, bg=C["bg"], padx=14, pady=10)
            box.pack(side="left", fill="x", expand=True, padx=(0, 10))
            tk.Label(box, text=label, bg=C["bg"], fg=C["muted"], font=F(9)).pack(anchor="w")
            v = tk.Label(box, text="-", bg=C["bg"], fg=C["text"], font=F(13, "bold"))
            v.pack(anchor="w", pady=(2, 0))
            self.stat_vals[key] = v
        hline(prog)
        self.job_area = tk.Frame(prog, bg=C["card"])
        self.job_area.pack(fill="x")
        self._job_area_mode = None
        self._build_job_area()

        # 오늘 한 일
        today = datetime.now().date()
        hist_all = read_history()
        todays = [h for h in reversed(hist_all) if h.get("time", "")[:10] == today.isoformat()]
        week_start = today - timedelta(days=today.weekday())
        week_n = sum(1 for h in hist_all if h.get("status") in ("published", "draft")
                     and h.get("time", "")[:10] >= week_start.isoformat())
        recent = card(left, f"오늘 한 일 · {today:%Y-%m-%d}", "기록 폴더 열기", self.on_open_folder)
        recent.pack(fill="x", pady=(20, 0))
        tk.Label(recent, text=f"이번 주 쓴 글 {week_n}편", bg=C["card"], fg=C["muted"], font=F(9),
                 anchor="w").pack(fill="x", padx=20)
        if not todays:
            tk.Label(recent, text="오늘은 아직 한 일이 없어요", bg=C["card"], fg=C["text"], font=F(10, "bold"),
                     anchor="w").pack(fill="x", padx=20, pady=(10, 2))
            tk.Label(recent, text="오른쪽 위 '새 글 쓰기'나 오른쪽 아래 '자동 등록 시작'을 누르면 여기에 쌓여요.",
                     bg=C["card"], fg=C["muted"], font=F(9), anchor="w").pack(fill="x", padx=20, pady=(0, 16))
            older = [h for h in reversed(hist_all)][:3]
            if older:
                hline(recent)
                tk.Label(recent, text="지난 작업", bg=C["card"], fg=C["muted"], font=F(9, "bold"),
                         anchor="w").pack(fill="x", padx=20, pady=(10, 0))
                for h in older:
                    self._history_row(recent, h)
        for i, h in enumerate(todays[:10]):
            if i:
                hline(recent)
            self._history_row(recent, h)
        tk.Frame(recent, bg=C["card"], height=6).pack()

        # 오른쪽: 바로 시작
        quick = card(right, "바로 시작")
        quick.pack(fill="x")
        for label, cmd in (("새 글 쓰기 (주제·편수 정하기)", self.on_new_post),
                           ("네이버 로그인 확인", self.on_login), ("키워드 관리", lambda: self.show("keywords")),
                           ("기록 폴더 열기", self.on_open_folder),
                           ("바탕화면 아이콘 만들기", self.on_shortcut)):
            self._quick_row(quick, label, cmd)
        tk.Frame(quick, bg=C["card"], height=10).pack()

        # 오른쪽 아래 고정: 원클릭 자동 등록 (스크롤과 상관없이 항상 보이게 창 오른쪽 아래에 띄움)
        tk.Frame(right, bg=C["bg"], height=300).pack(fill="x")      # 떠 있는 카드에 가리지 않게 자리 비움
        one = tk.Frame(self.main, bg=C["card"], highlightthickness=2, highlightbackground=C["primary"])
        one.place(relx=1.0, rely=1.0, anchor="se", x=-40, y=-20, width=330)
        tk.Label(one, text="원클릭 자동 등록", bg=C["card"], fg=C["text"], font=F(12, "bold"),
                 anchor="w").pack(fill="x", padx=20, pady=(14, 4))
        mode = "임시저장" if self.cfg.publish_mode == "draft" else "바로 발행"
        self.one_desc = tk.Label(one, justify="left", anchor="w", bg=C["card"], fg=C["muted"], font=F(9),
                                 wraplength=285)
        self.one_desc.pack(fill="x", padx=20)
        tk.Label(one, text=f"다 쓰면: {mode}", bg=C["card"], fg=C["text"], font=F(9, "bold"),
                 anchor="w").pack(fill="x", padx=20, pady=(6, 0))
        tk.Label(one, text=(f"안전장치: 하루 최대 {self.cfg.daily_limit}개 · 글 사이 {self.cfg.interval_min_minutes}~"
                            f"{self.cfg.interval_max_minutes}분 · {self.cfg.active_start_hour}~{self.cfg.active_end_hour}시"),
                 bg=C["card"], fg=C["muted"], font=F(8), anchor="w").pack(fill="x", padx=20, pady=(2, 0))
        self.big_btn = Btn(one, "▶  자동 등록 시작", self.on_toggle, size=13, pady=16)
        self.big_btn.pack(fill="x", padx=20, pady=(10, 8))
        Btn(one, "✎  한 편만 수동으로 쓰기", self.on_new_post, kind="soft", size=10, pady=8).pack(
            fill="x", padx=20, pady=(0, 16))
        one.lift()
        self._refresh_home()

    # ------------------------------------------------------------ 진행 카드 (작성 중 / 끝난 글 / 기록)
    def _job_mode(self) -> str:
        job = self.runner.job
        if job and not job.get("done"):
            return "job"
        if job and job.get("done") and not job.get("dismissed"):
            return "result"
        return "log"

    def _build_job_area(self):
        mode = self._job_mode()
        if mode == self._job_area_mode:
            return
        self._job_area_mode = mode
        self._jv = {}
        for w in self.job_area.winfo_children():
            w.destroy()
        if mode in ("log", "result"):
            self._build_idle_progress(self.job_area)
        if mode == "result":
            self._build_result_card(self.job_area, self.runner.job)
        if mode in ("log", "result"):
            self.home_log = tk.Text(self.job_area, height=8, bg=C["card"], fg=C["text"], font=F(9), relief="flat",
                                    padx=20, pady=12, wrap="word", state="disabled", highlightthickness=0)
            self.home_log.pack(fill="x")
            self.home_log.tag_configure("muted", foreground=C["muted"])
            self._render_log(self.home_log, self.log_lines[-40:])
            return
        self._build_job_view(self.job_area)

    def _build_idle_progress(self, parent):
        """작성 중이 아닐 때도 진행 그래프(원형·막대)를 항상 보여 준다: 시작 전 0%, 다음 글 대기, 방금 끝난 글 100%."""
        jv = self._jv
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", padx=20, pady=(14, 4))
        jv["i_donut"] = tk.Canvas(row, width=120, height=120, bg=C["card"], highlightthickness=0)
        jv["i_donut"].pack(side="left")
        rt = tk.Frame(row, bg=C["card"])
        rt.pack(side="left", fill="both", expand=True, padx=(18, 0))
        jv["i_stage"] = tk.Label(rt, bg=C["card"], fg=C["text"], font=F(14, "bold"), anchor="w")
        jv["i_stage"].pack(fill="x", pady=(14, 0))
        jv["i_sub"] = tk.Label(rt, bg=C["card"], fg=C["muted"], font=F(9), anchor="w")
        jv["i_sub"].pack(fill="x", pady=(2, 8))
        jv["i_bar"] = tk.Canvas(rt, height=22, bg=C["card"], highlightthickness=0)
        jv["i_bar"].pack(fill="x")
        btns = tk.Frame(rt, bg=C["card"])
        btns.pack(fill="x", pady=(10, 0))
        Btn(btns, "✎  한 편 바로 쓰기 (수동)", self.on_new_post, size=10, padx=16, pady=7).pack(side="left")
        jv["i_auto"] = Btn(btns, "▶  자동 등록 시작", self.on_toggle, kind="soft", size=10, padx=16, pady=7)
        jv["i_auto"].pack(side="left", padx=8)

    def _refresh_idle_progress(self):
        jv = self._jv
        if "i_donut" not in jv or not jv["i_donut"].winfo_exists():
            return
        job = self.runner.job
        st = self.runner.state if self.runner.running else "idle"
        if st == "waiting":
            ok, reason, wait = self.runner.gate()
            at = datetime.now() + timedelta(seconds=wait)
            gap = (self.runner.next_gap_minutes or self.cfg.interval_min_minutes) * 60
            pct = int(max(0, min(99, 100 * (1 - wait / gap)))) if gap and not ok else 0
            stage, sub, cap = "다음 글 기다리는 중", f"{at:%m/%d %H:%M}에 다음 글을 써요 · {reason}", "대기"
        elif job and job.get("done") and not job.get("dismissed"):
            pct = 100 if job.get("status") in ("published", "draft") else display_pct(job)
            stage = "방금 글 한 편을 마쳤어요" if pct == 100 else "방금 작업이 멈췄어요"
            sub, cap = (job.get("title") or job.get("topic", ""))[:60], "완료" if pct == 100 else "중단"
        elif self.runner.running:
            pct, stage, sub, cap = 0, "주제를 고르는 중", "곧 자료 수집을 시작해요", "준비"
        else:
            pct, stage, cap = 0, "시작 전이에요", "시작 전"
            sub = "오른쪽 아래 '자동 등록 시작' 또는 '한 편 바로 쓰기'를 누르면 진행률이 여기에 보여요."
        draw_donut(jv["i_donut"], pct, 120, cap)
        draw_bar(jv["i_bar"], pct, 22)
        jv["i_stage"].configure(text=stage)
        jv["i_sub"].configure(text=sub)
        if self.runner.running:
            jv["i_auto"].configure(text="■  자동 등록 멈추기")
        else:
            jv["i_auto"].configure(text="▶  자동 등록 시작")

    def _build_result_card(self, parent, job):
        st = job.get("status") or ""
        ok = st in ("published", "draft")
        head_text = {"published": "발행까지 마쳤어요", "draft": "임시저장까지 마쳤어요"}.get(
            st, "확인이 필요해요" if st in COUNTED else "이번 주제는 건너뛰었어요")
        color, bg = (C["ok"], C["ok_bg"]) if ok else ((C["warn"], C["warn_bg"]) if st in COUNTED or st == "blocked"
                                                      else (C["muted"], C["hover"]))
        box = tk.Frame(parent, bg=C["card"], highlightthickness=2, highlightbackground=color)
        box.pack(fill="x", padx=20, pady=(14, 6))
        top = tk.Frame(box, bg=C["card"])
        top.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(top, text="✓" if ok else "!", bg=color, fg="white", font=F(14, "bold"), width=2).pack(side="left")
        tt = tk.Frame(top, bg=C["card"])
        tt.pack(side="left", padx=12, fill="x", expand=True)
        tk.Label(tt, text=head_text, bg=C["card"], fg=color, font=F(13, "bold"), anchor="w").pack(fill="x")
        sub = (f"네이버 · {self.cfg.naver_blog_id} · " + ("임시저장함에서 확인할 수 있어요" if st == "draft" else
               "블로그에 올라갔어요" if st == "published" else job.get("reason", "")[:80]))
        tk.Label(tt, text=sub, bg=C["card"], fg=C["muted"], font=F(9), anchor="w").pack(fill="x")
        tk.Label(top, text="닫기 ✕", bg=C["card"], fg=C["faint"], font=F(9), cursor="hand2").pack(side="right")
        top.winfo_children()[-1].bind("<Button-1>", lambda e: self._dismiss_result())
        if ok or st in COUNTED:
            stats = tk.Frame(box, bg=C["card"])
            stats.pack(fill="x", padx=16, pady=6)
            el = job.get("elapsed", 0)
            chars = job.get("chars") or 0
            for val, lab in ((f"{el // 60}분 {el % 60:02d}초", "걸린 시간"), (f"{chars:,}자", "글 분량"),
                             (f"{job.get('photos_total', 0)}장", "사진")):
                c = tk.Frame(stats, bg=C["card"], highlightthickness=1, highlightbackground=C["line"], padx=14, pady=8)
                c.pack(side="left", fill="x", expand=True, padx=(0, 8))
                tk.Label(c, text=val, bg=C["card"], fg=C["text"], font=F(14, "bold"), anchor="w").pack(fill="x")
                tk.Label(c, text=lab, bg=C["card"], fg=C["muted"], font=F(9), anchor="w").pack(fill="x")
        info = tk.Frame(box, bg=C["card"])
        info.pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(info, text=f"주제: {job.get('topic', '')}", bg=C["card"], fg=C["muted"], font=F(9),
                 anchor="w").pack(fill="x")
        if job.get("title"):
            tk.Label(info, text=f"쓴 제목: {job['title']}", bg=C["card"], fg=C["text"], font=F(11, "bold"),
                     anchor="w").pack(fill="x", pady=(2, 0))
        btns = tk.Frame(box, bg=C["card"])
        btns.pack(fill="x", padx=16, pady=(8, 14))
        url = job.get("url") or f"https://blog.naver.com/{self.cfg.naver_blog_id}"
        Btn(btns, "한 편 더", self.on_new_post, kind="ghost", size=9, padx=14, pady=6).pack(side="right")
        folder = Path(job.get("folder", ""))
        if (folder / "preview.html").exists():
            Btn(btns, "미리보기", lambda: self._open_path(folder / "preview.html"), kind="ghost", size=9,
                padx=14, pady=6).pack(side="right", padx=6)
        if folder.exists():
            Btn(btns, "자료·추론 보기", lambda: self._open_path(folder), kind="ghost", size=9, padx=14,
                pady=6).pack(side="right")
        if ok or st in COUNTED:
            Btn(btns, "글 열기", lambda: webbrowser.open(url), size=9, padx=16, pady=6).pack(side="right", padx=6)

    def _dismiss_result(self):
        if self.runner.job:
            self.runner.job["dismissed"] = True
        self._refresh_job_area()

    def _build_job_view(self, a):
        from .runner import STEPS
        jv = self._jv
        top = tk.Frame(a, bg=C["card"])
        top.pack(fill="x", padx=20, pady=(14, 2))
        jv["head"] = tk.Label(top, bg=C["card"], fg=C["primary_dk"], font=F(10, "bold"))
        jv["head"].pack(side="left")
        Btn(top, "멈추기", self.on_stop_job, kind="danger", size=9, padx=12, pady=5).pack(side="right")
        Btn(top, "블로그 화면 보기/숨기기", self.on_toggle_view, kind="ghost", size=9, padx=12, pady=5).pack(
            side="right", padx=6)
        jv["topic"] = autowrap(tk.Label(a, bg=C["card"], fg=C["text"], font=F(12, "bold"), anchor="w",
                                        justify="left"))
        jv["topic"].pack(fill="x", padx=20, pady=(4, 0))
        jv["title"] = autowrap(tk.Label(a, bg=C["card"], fg=C["text"], font=F(13, "bold"), anchor="w",
                                        justify="left"))
        jv["title"].pack(fill="x", padx=20)
        jv["finish"] = tk.Label(a, bg=C["card"], fg=C["muted"], font=F(9), anchor="w")
        jv["finish"].pack(fill="x", padx=20, pady=(2, 6))
        line = tk.Frame(a, bg=C["card"])
        line.pack(fill="x", padx=20)
        jv["now"] = tk.Label(line, bg=C["card"], fg=C["text"], font=F(10), anchor="w")
        jv["now"].pack(side="left")
        jv["eta"] = tk.Label(line, bg=C["card"], fg=C["muted"], font=F(9))
        jv["eta"].pack(side="right")

        prog = tk.Frame(a, bg=C["card"])
        prog.pack(fill="x", padx=20, pady=(8, 6))
        jv["donut"] = tk.Canvas(prog, width=140, height=140, bg=C["card"], highlightthickness=0)
        jv["donut"].pack(side="left")
        pr = tk.Frame(prog, bg=C["card"])
        pr.pack(side="left", fill="both", expand=True, padx=(18, 0))
        jv["stage"] = tk.Label(pr, bg=C["card"], fg=C["text"], font=F(14, "bold"), anchor="w")
        jv["stage"].pack(fill="x", pady=(10, 0))
        jv["stage_sub"] = tk.Label(pr, bg=C["card"], fg=C["muted"], font=F(9), anchor="w")
        jv["stage_sub"].pack(fill="x", pady=(2, 8))
        jv["bar"] = tk.Canvas(pr, height=26, bg=C["card"], highlightthickness=0)
        jv["bar"].pack(fill="x")
        cnt = tk.Frame(pr, bg=C["card"])
        cnt.pack(fill="x", pady=(10, 0))
        jv["cnt"] = []
        for lab in ("옮긴 부분", "사진"):
            c = tk.Frame(cnt, bg=C["bg"], padx=12, pady=6)
            c.pack(side="left", fill="x", expand=True, padx=(0, 8))
            v = tk.Label(c, text="-", bg=C["bg"], fg=C["text"], font=F(12, "bold"), anchor="w")
            v.pack(fill="x")
            tk.Label(c, text=lab, bg=C["bg"], fg=C["muted"], font=F(8), anchor="w").pack(fill="x")
            jv["cnt"].append(v)

        cols = tk.Frame(a, bg=C["card"])
        cols.pack(fill="x", padx=20, pady=(8, 4))
        cols.columnconfigure(0, weight=3, uniform="c")
        cols.columnconfigure(1, weight=2, uniform="c")
        leftc = tk.Frame(cols, bg=C["card"])
        leftc.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        rightc = tk.Frame(cols, bg=C["card"])
        rightc.grid(row=0, column=1, sticky="nsew")

        # 왼쪽 위: 이번 글 정보
        info = tk.Frame(leftc, bg=C["card"], highlightthickness=1, highlightbackground=C["line"])
        info.pack(fill="x")
        tk.Label(info, text="이번 글 정보", bg=C["card"], fg=C["muted"], font=F(9), anchor="w").pack(
            fill="x", padx=14, pady=(10, 4))
        grid = tk.Frame(info, bg=C["card"])
        grid.pack(fill="x", padx=14, pady=(0, 10))
        jv["info"] = {}
        for i, (k, lab) in enumerate((("style", "말투"), ("finish", "끝나면"), ("rule", "검증"))):
            f = tk.Frame(grid, bg=C["card"])
            f.grid(row=0, column=i, sticky="w", padx=(0, 28))
            tk.Label(f, text=lab, bg=C["card"], fg=C["muted"], font=F(8), anchor="w").pack(fill="x")
            v = tk.Label(f, bg=C["card"], fg=C["text"], font=F(10), anchor="w")
            v.pack(fill="x")
            jv["info"][k] = v

        # 왼쪽 아래: 순서(준비 중) 또는 옮기는 중 미리보기
        jv["mid"] = tk.Frame(leftc, bg=C["card"], highlightthickness=1, highlightbackground=C["line"])
        jv["mid"].pack(fill="both", expand=True, pady=(10, 0))
        jv["mid_mode"] = None

        # 오른쪽: 방금 한 일 + 이 블로그의 기록
        ev = tk.Frame(rightc, bg=C["card"], highlightthickness=1, highlightbackground=C["line"])
        ev.pack(fill="x")
        tk.Label(ev, text="방금 한 일", bg=C["card"], fg=C["text"], font=F(11, "bold"), anchor="w").pack(
            fill="x", padx=14, pady=(10, 4))
        jv["events"] = tk.Text(ev, height=9, bg=C["card"], fg=C["text"], font=F(9), relief="flat", padx=14,
                               pady=2, wrap="none", state="disabled", highlightthickness=0, cursor="arrow")
        jv["events"].pack(fill="x", pady=(0, 10))
        jv["events"].tag_configure("t", foreground=C["muted"])
        jv["events"].tag_configure("b", font=F(9, "bold"))
        jv["events"].tag_configure("tb", foreground=C["text"], font=F(9, "bold"))
        rec = tk.Frame(rightc, bg=C["card"], highlightthickness=1, highlightbackground=C["line"])
        rec.pack(fill="x", pady=(10, 0))
        tk.Label(rec, text="이 블로그의 기록", bg=C["card"], fg=C["muted"], font=F(9), anchor="w").pack(
            fill="x", padx=14, pady=(10, 4))
        g = tk.Frame(rec, bg=C["card"])
        g.pack(fill="x", padx=14, pady=(0, 10))
        for i, (lab, val) in enumerate(self._blog_record()):
            f = tk.Frame(g, bg=C["card"])
            f.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 26), pady=3)
            tk.Label(f, text=lab, bg=C["card"], fg=C["muted"], font=F(8), anchor="w").pack(fill="x")
            tk.Label(f, text=val, bg=C["card"], fg=C["text"], font=F(10), anchor="w").pack(fill="x")

        # 아래: 단계 막대
        seg = tk.Frame(a, bg=C["card"])
        seg.pack(fill="x", padx=20, pady=(14, 4))
        jv["seg"] = []
        for i, name in enumerate(STEPS):
            seg.columnconfigure(i, weight=1, uniform="s")
            f = tk.Frame(seg, bg=C["card"])
            f.grid(row=0, column=i, sticky="we", padx=(0 if i == 0 else 4, 0))
            bar = tk.Frame(f, height=4, bg=C["line"])
            bar.pack(fill="x")
            nm = tk.Label(f, text=f"{i + 1}  {name}", bg=C["card"], fg=C["muted"], font=F(9, "bold"), anchor="w")
            nm.pack(fill="x", pady=(6, 0))
            tm = tk.Label(f, bg=C["card"], fg=C["muted"], font=F(8), anchor="w")
            tm.pack(fill="x")
            jv["seg"].append((bar, nm, tm))

        # 기다리는 동안: 다 쓰면
        fin = tk.Frame(a, bg=C["card"])
        fin.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(fin, text="기다리는 동안 정해 두세요 · 다 쓰면", bg=C["card"], fg=C["text"], font=F(10, "bold"),
                 anchor="w").pack(fill="x")
        row = tk.Frame(fin, bg=C["card"])
        row.pack(fill="x", pady=(8, 0))
        jv["fin_btns"] = {}
        for mode, lab in (("draft", "임시저장만 해 두기"), ("publish", "바로 올리기")):
            b = Btn(row, lab, lambda m=mode: self.on_finish_mode(m), kind="ghost", size=10, padx=16, pady=7)
            b.pack(side="left", padx=(0, 8))
            jv["fin_btns"][mode] = b
        tk.Label(a, text="다른 메뉴를 보거나 PC로 다른 일을 해도 글쓰기는 계속돼요. MYDAF 창을 닫으면 멈춰요.\n"
                         "네이버 편집기에 옮기는 동안에는 열린 블로그 창을 닫지 마세요.",
                 bg=C["primary_bg"], fg=C["primary_dk"], font=F(9), anchor="w", justify="left", padx=14,
                 pady=10).pack(fill="x", padx=20, pady=(10, 18))

    def _blog_record(self) -> list[tuple[str, str]]:
        hist = read_history()
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())
        written = [h for h in hist if h.get("status") in ("published", "draft")]
        n_today = sum(1 for h in written if h.get("time", "")[:10] == today.isoformat())
        n_week = sum(1 for h in written if h.get("time", "")[:10] >= week_start.isoformat())
        times = [h["elapsed"] for h in written if h.get("elapsed")]
        fmt = lambda s: f"{s // 60}분 {s % 60:02d}초"
        return [("오늘", f"{n_today}편 썼어요"), ("이번 주", f"{n_week}편 썼어요"),
                ("지난 글", fmt(times[-1]) + " 걸렸어요" if times else "기록 없음"),
                ("가장 빨랐던 글", fmt(min(times)) if times else "기록 없음")]

    def _build_mid(self, job, mode):
        jv = self._jv
        mid = jv["mid"]
        for w in mid.winfo_children():
            w.destroy()
        jv["mid_mode"] = mode
        if mode == "steps":
            from .runner import STEPS
            tk.Label(mid, text="이 순서로 써요", bg=C["card"], fg=C["muted"], font=F(9), anchor="w").pack(
                fill="x", padx=14, pady=(10, 4))
            desc = ["뉴스·구글·KISS·RSS에서 자료 모으기", "사실 뽑기, 원문 대조, 매체 2곳 이상 교차 확인",
                    "검증된 사실로 초안 → 편집장 검토·수정", "소제목마다 자유 라이선스 사진 찾기",
                    "블로그 글쓰기 창에 글과 사진 넣기", "임시저장·발행이 됐는지 확인"]
            jv["steps"] = []
            for i, name in enumerate(STEPS):
                r = tk.Frame(mid, bg=C["card"])
                r.pack(fill="x", padx=14, pady=2)
                n = tk.Label(r, text=str(i + 1), bg=C["hover"], fg=C["muted"], font=F(8, "bold"), width=2)
                n.pack(side="left")
                t = tk.Label(r, text=name, bg=C["card"], fg=C["text"], font=F(9, "bold"))
                t.pack(side="left", padx=(8, 6))
                tk.Label(r, text=desc[i], bg=C["card"], fg=C["muted"], font=F(9)).pack(side="left")
                tm = tk.Label(r, bg=C["card"], fg=C["muted"], font=F(9))
                tm.pack(side="right")
                jv["steps"].append((n, t, tm))
            n_hist = sum(1 for h in read_history() if h.get("step_times"))
            tk.Label(mid, text=(f"지난 글 {min(n_hist, 7)}편을 쓴 기록으로 계산한 시간이에요." if n_hist
                                else "아직 기록이 없어 기본 예상 시간으로 보여 드려요."),
                     bg=C["card"], fg=C["faint"], font=F(8), anchor="w").pack(fill="x", padx=14, pady=(6, 10))
            return
        # 옮기는 중 미리보기
        jv["pv_head"] = tk.Label(mid, bg=C["card"], fg=C["muted"], font=F(9), anchor="w")
        jv["pv_head"].pack(fill="x", padx=14, pady=(10, 2))
        jv["pv_title"] = autowrap(tk.Label(mid, text=job.get("title", ""), bg=C["card"], fg=C["text"],
                                           font=F(12, "bold"), anchor="w", justify="left"))
        jv["pv_title"].pack(fill="x", padx=14)
        jv["pv_outline"] = []
        ol = tk.Frame(mid, bg=C["card"])
        ol.pack(fill="x", padx=24, pady=(6, 4))
        for i, h in enumerate(job.get("outline", [])):
            lab = tk.Label(ol, text=f"{i + 1}. {h}", bg=C["card"], fg=C["text"], font=F(9), anchor="w")
            lab.pack(fill="x")
            jv["pv_outline"].append(lab)
        tk.Label(mid, text="지금 옮기는 부분", bg=C["card"], fg=C["primary_dk"], font=F(10, "bold"),
                 anchor="w").pack(fill="x", padx=14, pady=(6, 2))
        jv["pv_now"] = tk.Text(mid, height=6, bg=C["card"], fg=C["text"], font=F(9), relief="flat", padx=14,
                               wrap="word", state="disabled", highlightthickness=0, cursor="arrow")
        jv["pv_now"].pack(fill="x")
        jv["pv_now"].tag_configure("ok", foreground=C["ok"])
        jv["pv_now"].tag_configure("h", font=F(10, "bold"), foreground=C["ok"])
        jv["pv_now"].tag_configure("cur", foreground=C["primary_dk"], font=F(9, "bold"))
        tk.Label(mid, text="실제 글쓰기 창은 위의 '블로그 화면 보기/숨기기'로 볼 수 있어요.", bg=C["card"],
                 fg=C["faint"], font=F(8), anchor="w").pack(fill="x", padx=14, pady=(2, 10))
        jv["pv_key"] = None

    def _refresh_job_area(self):
        if self.current != "home" or not getattr(self, "job_area", None) or not self.job_area.winfo_exists():
            return
        self._build_job_area()
        job = self.runner.job
        if self._job_area_mode != "job":
            self._refresh_idle_progress()
            return
        from .runner import STEPS, remaining_seconds
        jv = self._jv
        now = time.time()
        idx = job["step"]
        typical = job.get("typical") or [60] * len(STEPS)
        pct = display_pct(job)
        fmt = lambda s: f"{int(s) // 60}분 {int(s) % 60:02d}초" if s >= 60 else f"{int(s)}초"
        el = now - job["started"]
        in_step = now - job.get("step_started", job["started"])
        jv["head"].configure(text=f"지금 쓰는 중 · {idx + 1}/{len(STEPS)}단계")
        jv["topic"].configure(text=("주제: " if job.get("title") else "") + job["topic"],
                              font=F(10) if job.get("title") else F(12, "bold"),
                              fg=C["muted"] if job.get("title") else C["text"])
        jv["title"].configure(text=f"쓴 제목: {job['title']}" if job.get("title") else "")
        if not job.get("title"):
            jv["title"].pack_forget()
        elif not jv["title"].winfo_ismapped():
            jv["title"].pack(fill="x", padx=20, after=jv["topic"])
        fin = job.get("finish_mode", "draft")
        jv["finish"].configure(text="끝나면 바로 올려요" if fin == "publish" else "끝나면 임시저장해 둬요")
        last = job["events"][-1][1] if job["events"] else STEPS[idx]
        jv["now"].configure(text="● " + last[:70])
        jv["eta"].configure(text=f"{fmt(el)} 지남 · 약 {max(1, round(remaining_seconds(job, typical, now) / 60))}분 남았어요")
        draw_donut(jv["donut"], pct, 140, f"{idx + 1}/{len(STEPS)} 단계")
        draw_bar(jv["bar"], pct, 26)
        jv["stage"].configure(text=f"{STEPS[idx]} 중")
        jv["stage_sub"].configure(text=f"{fmt(in_step)}째 · 보통 {fmt(typical[idx])} · 전체 진행률 {pct}%")
        bt, bd = job.get("blocks_total", 0), job.get("blocks_done", 0)
        pt, pd = job.get("photos_total", 0), job.get("photos_done", 0)
        moving = idx >= 4 and bt
        jv["cnt"][0].configure(text=f"{bd}/{bt}" if moving else "옮기기 전")
        jv["cnt"][1].configure(text=f"{pd}/{pt}장" if moving and pt else ("사진 없음" if moving else "옮기기 전"))
        jv["info"]["style"].configure(text=job.get("style", ""))
        jv["info"]["finish"].configure(text="바로 올리기" if fin == "publish" else "임시저장")
        jv["info"]["rule"].configure(text=f"출처 {self.cfg.min_independent_sources}곳+ · 사실 {self.cfg.min_verified_facts}개+")
        for m, b in jv["fin_btns"].items():
            b.restyle(b.cget("text"), "primary") if m == fin else self._ghost(b)

        want = "preview" if idx >= 4 and job.get("blocks") else "steps"
        if jv["mid_mode"] != want:
            self._build_mid(job, want)
        if want == "steps":
            for i, (n, t, tm) in enumerate(jv["steps"]):
                times = job.get("step_times") or [0] * len(STEPS)
                if i < idx:
                    n.configure(text="✓", bg=C["ok"], fg="white")
                    t.configure(fg=C["text"])
                    tm.configure(text=fmt(times[i]) if times[i] else "건너뜀", fg=C["muted"])
                elif i == idx:
                    n.configure(text=str(i + 1), bg=C["primary"], fg="white")
                    t.configure(fg=C["primary_dk"])
                    tm.configure(text=f"{fmt(in_step)}째 · 보통 {fmt(typical[i])}", fg=C["primary_dk"])
                else:
                    n.configure(text=str(i + 1), bg=C["hover"], fg=C["muted"])
                    t.configure(fg=C["text"])
                    tm.configure(text=f"보통 {fmt(typical[i])}", fg=C["muted"])
        else:
            self._refresh_preview(job)

        times = job.get("step_times") or [0] * len(STEPS)
        for i, (bar, nm, tm) in enumerate(jv["seg"]):
            if i < idx:
                bar.configure(bg=C["ok"])
                nm.configure(text=f"✓  {STEPS[i]}", fg=C["text"])
                tm.configure(text=fmt(times[i]) if times[i] else "-", fg=C["muted"])
            elif i == idx:
                bar.configure(bg=C["primary"])
                nm.configure(text=f"{i + 1}  {STEPS[i]}", fg=C["primary_dk"])
                tm.configure(text=f"{fmt(in_step)}째 · 보통 {fmt(typical[i])}", fg=C["primary_dk"])
            else:
                bar.configure(bg=C["line"])
                nm.configure(text=f"{i + 1}  {STEPS[i]}", fg=C["muted"])
                tm.configure(text=f"보통 {fmt(typical[i])}", fg=C["muted"])

        evs = job["events"][-9:]
        key = (len(job["events"]), int(el))
        if jv.get("ev_key") != key:
            jv["ev_key"] = key
            t = jv["events"]
            t.configure(state="normal")
            t.delete("1.0", "end")
            for j, (ts, m) in enumerate(reversed(evs)):
                rel = self._rel_time(job, ts)
                t.insert("end", f"{rel:>8}   ", "tb" if j == 0 else "t")
                t.insert("end", m[:60] + "\n", "b" if j == 0 else ())
            t.configure(state="disabled")

    @staticmethod
    def _rel_time(job, ts: str) -> str:
        try:
            start = datetime.fromtimestamp(job["started"])
            at = datetime.combine(start.date(), datetime.strptime(ts, "%H:%M:%S").time())
            s = max(0, int((at - start.replace(microsecond=0)).total_seconds()))
        except (ValueError, KeyError):
            return ts
        return f"{s // 60}분 {s % 60}초" if s >= 60 else f"{s}초"

    def _refresh_preview(self, job):
        jv = self._jv
        blocks = job.get("blocks", [])
        cur = job.get("current")
        bd, bt = job.get("blocks_done", 0), job.get("blocks_total", 0)
        jv["pv_head"].configure(text=f"블로그로 옮기는 중 · 문단 {bd}/{bt} · 사진 {job.get('photos_done', 0)}장 들어감")
        # 목차: 지나간 소제목은 ✓
        n_head_done = sum(1 for b in blocks[:cur if cur is not None else len(blocks)] if b["type"] == "heading")
        for i, lab in enumerate(jv["pv_outline"]):
            name = job["outline"][i]
            if i < n_head_done:
                lab.configure(text=f"{i + 1}. ✓ {name}", fg=C["ok"])
            else:
                lab.configure(text=f"{i + 1}. {name}", fg=C["text"])
        key = (cur, bd)
        if jv.get("pv_key") == key:
            return
        jv["pv_key"] = key
        t = jv["pv_now"]
        t.configure(state="normal")
        t.delete("1.0", "end")
        end = cur if cur is not None else len(blocks)
        for b in blocks[max(0, end - 3):end]:
            if b["type"] == "heading":
                t.insert("end", "✓ " + b["text"] + "\n", "h")
            elif b["type"] == "image":
                t.insert("end", "✓ 사진 1장\n", "ok")
            else:
                t.insert("end", "✓ ", "ok")
                t.insert("end", b.get("text", "")[:150] + "\n")
        if cur is not None and cur < len(blocks):
            b = blocks[cur]
            label = "사진 1장" if b["type"] == "image" else b.get("text", "")[:150]
            t.insert("end", label + " · 옮기는 중\n", "cur")
        t.configure(state="disabled")
        t.see("end")

    def _ghost(self, b):
        b.bg, b.hover = C["card"], C["hover"]
        b.configure(bg=C["card"], fg=C["primary_dk"])

    def on_finish_mode(self, mode):
        self.runner.set_finish_mode(mode)
        self._refresh_job_area()

    def on_stop_job(self):
        self.runner.stop()
        self.msgs.put("멈춤 요청: 지금 하던 단계까지 마치고 멈춰요.")

    # ------------------------------------------------------------ 새 글 쓰기 창
    def on_new_post(self):
        if not self._ready():
            return
        if not self.runner.can_write_now:
            messagebox.showinfo("MYDAF", "지금 글을 쓰고 있어요. 끝난 뒤에 다시 눌러 주세요.")
            return
        win = tk.Toplevel(self.root)
        win.title("새 글 쓰기")
        win.configure(bg=C["card"])
        win.transient(self.root)
        win.resizable(False, False)
        pad = dict(padx=24)
        tk.Label(win, text="새 글 쓰기", bg=C["card"], fg=C["text"], font=F(15, "bold"), anchor="w").pack(
            fill="x", pady=(20, 2), **pad)
        tk.Label(win, text="주제와 편수를 정하면 바로 써요. 비워 두면 키워드에서 알아서 골라요.", bg=C["card"],
                 fg=C["muted"], font=F(9), anchor="w").pack(fill="x", **pad)
        tk.Label(win, text="글을 쓸 블로그", bg=C["card"], fg=C["text"], font=F(10, "bold"), anchor="w").pack(
            fill="x", pady=(16, 4), **pad)
        tk.Label(win, text=f"N  {self.cfg.naver_blog_id} · 네이버 · 로그인 {self.login_state}", bg=C["bg"],
                 fg=C["text"], font=F(10), anchor="w", padx=12, pady=8).pack(fill="x", **pad)
        tk.Label(win, text="어떤 글을 쓸까요", bg=C["card"], fg=C["text"], font=F(10, "bold"), anchor="w").pack(
            fill="x", pady=(16, 4), **pad)
        topic = tk.Entry(win, font=F(11), relief="solid", bd=1, width=52)
        topic.pack(fill="x", ipady=6, **pad)
        topic.focus_set()
        tk.Label(win, text="쉼표로 여러 개를 적으면 그중 2~3개를 골라 한 편으로 엮어요. 길이 제한 없어요.",
                 bg=C["card"], fg=C["muted"], font=F(9), anchor="w").pack(fill="x", pady=(4, 0), **pad)
        tk.Label(win, text=(f"글자 크기 · 소제목 {self.cfg.heading_font_size} · 본문 {self.cfg.body_font_size}"
                            f" · 말투 {self.cfg.writer_style} (글쓰기 설정에서 바꿔요)"),
                 bg=C["card"], fg=C["muted"], font=F(9), anchor="w").pack(fill="x", pady=(12, 0), **pad)

        left_today = max(0, self.cfg.daily_limit - self.runner.posted_today())
        count = tk.IntVar(value=1)
        mode = tk.StringVar(value=self.cfg.publish_mode)
        row = tk.Frame(win, bg=C["card"])
        row.pack(fill="x", pady=(16, 0), **pad)
        cbox = tk.Frame(row, bg=C["card"])
        cbox.pack(side="left")
        tk.Label(cbox, text="몇 편", bg=C["card"], fg=C["text"], font=F(10, "bold"), anchor="w").pack(fill="x")
        crow = tk.Frame(cbox, bg=C["card"])
        crow.pack(fill="x", pady=(4, 0))
        mbox = tk.Frame(row, bg=C["card"])
        mbox.pack(side="left", padx=(28, 0))
        tk.Label(mbox, text="다 쓰면", bg=C["card"], fg=C["text"], font=F(10, "bold"), anchor="w").pack(fill="x")
        mrow = tk.Frame(mbox, bg=C["card"])
        mrow.pack(fill="x", pady=(4, 0))
        seg = {"count": [], "mode": []}

        def paint():
            for n, b in seg["count"]:
                if n > max(left_today, 1):
                    b.configure(bg=C["hover"], fg=C["faint"])
                elif count.get() == n:
                    b.configure(bg=C["primary"], fg="white")
                else:
                    b.configure(bg=C["card"], fg=C["text"])
            for m, b in seg["mode"]:
                b.configure(bg=C["primary"] if mode.get() == m else C["card"],
                            fg="white" if mode.get() == m else C["text"])
            hint.configure(text=(f"오늘 더 쓸 수 있는 글: {left_today}편 (하루 최대 {self.cfg.daily_limit}편). "
                                 f"2편 이상이면 안전 간격(최소 {MIN_INTERVAL_FLOOR // 60}시간)을 지켜 이어서 써요."
                                 + (" 바로 올리기는 네이버에 공개로 올라가요." if mode.get() == "publish" else "")))

        for n in (1, 2, 3):
            b = tk.Label(crow, text=f"{n}편", font=F(10, "bold"), padx=14, pady=6, cursor="hand2",
                         highlightthickness=1, highlightbackground=C["line"])
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e, n=n: (n <= max(left_today, 1)) and (count.set(n), paint()))
            seg["count"].append((n, b))
        for m, lab in (("draft", "임시저장"), ("publish", "바로 올리기")):
            b = tk.Label(mrow, text=lab, font=F(10, "bold"), padx=16, pady=6, cursor="hand2",
                         highlightthickness=1, highlightbackground=C["line"])
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e, m=m: (mode.set(m), paint()))
            seg["mode"].append((m, b))
        hint = tk.Label(win, bg=C["card"], fg=C["muted"], font=F(9), anchor="w", justify="left", wraplength=470)
        hint.pack(fill="x", pady=(10, 0), **pad)
        paint()
        hline(win)
        foot = tk.Frame(win, bg=C["card"])
        foot.pack(fill="x", pady=16, **pad)

        def go():
            t = topic.get().strip()
            if mode.get() == "publish" and not messagebox.askyesno(
                    "바로 올리기", "다 쓰면 네이버에 바로 공개로 올려요. 이대로 시작할까요?", parent=win):
                return
            win.destroy()
            if left_today <= 0:
                messagebox.showinfo("MYDAF", f"오늘 한도 {self.cfg.daily_limit}편을 다 썼어요. 내일 다시 해 주세요.")
                return
            if not self.runner.start_batch(t or None, count.get(), mode.get()):
                messagebox.showinfo("MYDAF", "지금 글을 쓰고 있어요. 끝난 뒤에 다시 눌러 주세요.")
                return
            self.msgs.put("✎ 수동 글쓰기를 시작해요 (활동 시간·간격과 상관없이 지금 바로, 하루 한도는 지켜요)")
            self.show("home")

        Btn(foot, "글쓰기 시작", go, padx=22, pady=9).pack(side="right")
        Btn(foot, "닫기", win.destroy, kind="ghost", padx=18, pady=9).pack(side="right", padx=8)
        topic.bind("<Return>", lambda e: go())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()
        self._new_post_win = win

    def _quick_row(self, parent, label, cmd):
        row = tk.Frame(parent, bg=C["card"], highlightthickness=1, highlightbackground=C["line"], cursor="hand2")
        row.pack(fill="x", padx=20, pady=5)
        a = tk.Label(row, text=label, bg=C["card"], fg=C["text"], font=F(10), anchor="w")
        a.pack(side="left", padx=14, pady=11)
        b = tk.Label(row, text="›", bg=C["card"], fg=C["muted"], font=F(14))
        b.pack(side="right", padx=12)
        for w in (row, a, b):
            w.bind("<Button-1>", lambda e: cmd())
            w.bind("<Enter>", lambda e: [x.configure(bg=C["hover"]) for x in (row, a, b)])
            w.bind("<Leave>", lambda e: [x.configure(bg=C["card"]) for x in (row, a, b)])

    def _history_row(self, parent, h):
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", padx=20, pady=10)
        text, fg, bg = STATUS_CHIP.get(h.get("status"), (h.get("status", "?"), C["muted"], C["hover"]))
        line1 = tk.Frame(row, bg=C["card"])
        line1.pack(fill="x")
        chip(line1, text, fg, bg).pack(side="left")
        title = h.get("title") or h.get("topic", "")
        tk.Label(line1, text=title[:46], bg=C["card"], fg=C["text"], font=F(10, "bold")).pack(side="left", padx=8)
        when = h.get("time", "")[5:16].replace("T", " ")
        if h.get("status") in COUNTED:
            sub = f"{when} · 검증 사실 {h.get('facts', '-')}개 · 출처 {h.get('sources', '-')}곳 · 추론 {h.get('inferences', 0)}건"
        else:
            sub = f"{when} · {h.get('reason', '')}"
        tk.Label(row, text=sub[:90], bg=C["card"], fg=C["muted"], font=F(9), anchor="w").pack(fill="x", pady=(4, 0))
        btns = tk.Frame(line1, bg=C["card"])
        btns.pack(side="right")
        if h.get("url"):
            Btn(btns, "글 보기", lambda u=h["url"]: webbrowser.open(u), kind="soft", size=9, padx=12, pady=5).pack(
                side="left", padx=4)
        folder = POST_DIR / h.get("post_id", "")
        if h.get("post_id") and folder.exists():
            Btn(btns, "자료·추론 보기", lambda f=folder: self._open_path(f), kind="ghost", size=9, padx=10,
                pady=5).pack(side="left")

    def _refresh_home(self):
        if self.current != "home" or not hasattr(self, "big_btn"):
            return
        st = self.runner.status()
        running = self.runner.running
        names = {"idle": "대기 중", "running": "작성 중", "waiting": "다음 글 대기", "stopping": "멈추는 중"}
        state = names.get(st["state"], st["state"])
        if self.runner.job and not self.runner.job.get("done"):
            state = "작성 중"
        self.stat_vals["state"].configure(text=state, fg=C["primary_dk"] if running else C["text"])
        self.stat_vals["today"].configure(text=f"{st['today']} / {st['daily_limit']}")
        ok, reason, wait = self.runner.gate()
        nxt = "지금 가능" if ok else (datetime.now() + timedelta(seconds=wait)).strftime("%m/%d %H:%M")
        self.stat_vals["next"].configure(text=nxt)
        self.stat_vals["kw"].configure(text=f"{len(self.cfg.keywords)}개")
        if running:
            self.big_btn.restyle("■  자동 등록 멈추기", "danger")
            self.one_desc.configure(text="자동 등록이 켜져 있어요. 안전장치 기준에 맞춰 알아서 주제를 찾고, "
                                         "검증하고, 써서 올려요. 이 창은 켜두세요.")
        else:
            self.big_btn.restyle("▶  자동 등록 시작", "primary")
            self.one_desc.configure(text="한 번 누르면 주제 찾기 → 자료 수집 → 사실 검증 → 작성 → 네이버 등록을 "
                                         "계속 반복해요. 설정은 처음 한 번만 하면 돼요.")
        if hasattr(self, "head_status"):
            self.head_status.configure(text=("● 자동 등록 중" if running else "● 대기 중"),
                                       fg=C["ok"] if running else C["faint"])

    # ------------------------------------------------------------ 작업 기록
    def page_history(self):
        self.header("작업 기록")
        page = ScrollPage(self.main)
        page.pack(fill="both", expand=True)
        wrap = tk.Frame(page.inner, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=28, pady=24)
        lst = card(wrap, "전체 작업", "기록 폴더 열기", self.on_open_folder)
        lst.pack(fill="x")
        hist = list(reversed(read_history()))[:100]
        if not hist:
            tk.Label(lst, text="아직 작업 기록이 없어요", bg=C["card"], fg=C["muted"], font=F(10)).pack(
                anchor="w", padx=20, pady=(0, 16))
        for i, h in enumerate(hist):
            if i:
                hline(lst)
            self._history_row(lst, h)
        logc = card(wrap, "실행 로그", "로그 파일 열기", lambda: self._open_path(app_dir() / "logs"))
        logc.pack(fill="x", pady=(20, 0))
        self.hist_log = tk.Text(logc, height=16, bg=C["card"], font=F(9), relief="flat", padx=20, pady=12,
                                wrap="word", state="disabled", highlightthickness=0)
        self.hist_log.pack(fill="x")
        self._render_log(self.hist_log, self.log_lines[-300:])

    # ------------------------------------------------------------ 설정 화면
    def page_form(self, key):
        title, items = PAGES[key]
        self.header(title, right_widgets=False)
        page = ScrollPage(self.main)
        page.pack(fill="both", expand=True)
        wrap = tk.Frame(page.inner, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=28, pady=24)
        box = card(wrap)
        box.pack(fill="x")
        for i, (k, label, kind, help_) in enumerate(items):
            if i:
                hline(box)
            row = tk.Frame(box, bg=C["card"])
            row.pack(fill="x", padx=24, pady=14)
            row.columnconfigure(0, minsize=280)
            row.columnconfigure(1, weight=1)
            lab = tk.Frame(row, bg=C["card"])
            lab.grid(row=0, column=0, sticky="nw")
            tk.Label(lab, text=label, bg=C["card"], fg=C["text"], font=F(10, "bold"), anchor="w").pack(fill="x")
            if help_:
                tk.Label(lab, text=help_, bg=C["card"], fg=C["muted"], font=F(9), anchor="w", wraplength=260,
                         justify="left").pack(fill="x", pady=(2, 0))
            self._field(row, k, kind).grid(row=0, column=1, sticky="we", ipady=3)
        foot = tk.Frame(wrap, bg=C["bg"])
        foot.pack(fill="x", pady=16)
        Btn(foot, "저장", self.on_save, padx=28).pack(side="right")
        if key == "publish":
            Btn(foot, "처음 설정 다시 하기", self.show_setup, kind="ghost").pack(side="right", padx=10)

    def _field(self, parent, key, kind):
        value = getattr(self.cfg, key)
        if kind == "bool":
            v = tk.BooleanVar(value=value)
            self.vars[key] = v
            return tk.Checkbutton(parent, variable=v, bg=C["card"], activebackground=C["card"],
                                  text="사용", font=F(10), anchor="w")
        if kind == "lines":
            t = tk.Text(parent, height=8, font=F(10), relief="flat", highlightthickness=1,
                        highlightbackground=C["line"], highlightcolor=C["primary"], padx=8, pady=6)
            t.insert("1.0", "\n".join(value))
            self.vars[key] = t
            return t
        v = tk.StringVar(value=str(value))
        self.vars[key] = v
        if kind.startswith("combo:"):
            from tkinter import ttk
            return ttk.Combobox(parent, textvariable=v, values=kind[6:].split(","), font=F(10))
        if kind.startswith("choice:"):
            opts = kind[7:].split(",")
            m = tk.OptionMenu(parent, v, *opts)
            m.configure(font=F(10), bg=C["card"], relief="flat", highlightthickness=1,
                        highlightbackground=C["line"], anchor="w")
            return m
        return tk.Entry(parent, textvariable=v, show="•" if kind == "secret" else "", font=F(10), relief="flat",
                        highlightthickness=1, highlightbackground=C["line"], highlightcolor=C["primary"])

    def _collect(self) -> dict:
        return {k: (w.get("1.0", "end") if isinstance(w, tk.Text) else w.get()) for k, w in self.vars.items()
                if not k.startswith("_")}

    # ------------------------------------------------------------ 최초 설정 마법사
    def show_setup(self):
        self.current = "setup"
        self.clear_main()
        self._select_nav(None)
        self.header("처음 한 번만 설정해요", right_widgets=False)
        page = ScrollPage(self.main)
        page.pack(fill="both", expand=True)
        wrap = tk.Frame(page.inner, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=28, pady=24)
        tk.Label(wrap, text="4가지만 입력하면 다음부터는 '자동 등록 시작' 버튼 하나로 계속 올라가요.",
                 bg=C["bg"], fg=C["muted"], font=F(10)).pack(anchor="w", pady=(0, 14))

        def step(n, title, help_):
            box = card(wrap)
            box.pack(fill="x", pady=(0, 14))
            head = tk.Frame(box, bg=C["card"])
            head.pack(fill="x", padx=24, pady=(18, 6))
            tk.Label(head, text=str(n), bg=C["primary"], fg="white", font=F(10, "bold"), width=2).pack(side="left")
            tk.Label(head, text=title, bg=C["card"], fg=C["text"], font=F(12, "bold")).pack(side="left", padx=10)
            tk.Label(box, text=help_, bg=C["card"], fg=C["muted"], font=F(9), anchor="w").pack(fill="x", padx=24)
            body = tk.Frame(box, bg=C["card"])
            body.pack(fill="x", padx=24, pady=(8, 20))
            return body

        b = step(1, "글 쓸 AI와 API 키", "키는 이 PC에만 저장돼요. Gemini 는 Google AI Studio 에서 무료로 발급받을 수 있어요.")
        prov = tk.StringVar(value=self.cfg.ai_provider)
        self.vars["ai_provider"] = prov
        key = tk.StringVar(value=self.cfg.ai_key())
        self.setup_key = key
        hint = tk.Label(b, bg=C["card"], fg=C["muted"], font=F(9), anchor="w")
        keys = {"gemini": self.cfg.gemini_api_key, "claude": self.cfg.anthropic_api_key}
        last = {"p": prov.get()}

        def switch(*_):
            keys[last["p"]] = key.get()           # 고르기 전 입력값 보관
            last["p"] = prov.get()
            key.set(keys.get(prov.get(), ""))
            hint.configure(text={"gemini": "aistudio.google.com → Get API key (무료 · 하루 3개 글에 충분)",
                                 "claude": "console.anthropic.com → API Keys (유료 · 가장 고품질)"}[prov.get()])
        radios = tk.Frame(b, bg=C["card"])
        radios.pack(fill="x", pady=(0, 8))
        for val, txt in (("gemini", "Google Gemini (무료)"), ("claude", "Claude (유료)")):
            tk.Radiobutton(radios, text=txt, value=val, variable=prov, command=switch, bg=C["card"],
                           font=F(10, "bold"), activebackground=C["card"]).pack(side="left", padx=(0, 18))
        tk.Entry(b, textvariable=key, show="•", font=F(10), relief="flat", highlightthickness=1,
                 highlightbackground=C["line"], highlightcolor=C["primary"]).pack(fill="x", ipady=4)
        hint.pack(fill="x", pady=(6, 0))
        switch()
        b = step(2, "네이버 블로그 ID", "blog.naver.com/ 뒤에 오는 아이디")
        self._field(b, "naver_blog_id", "str").pack(fill="x", ipady=4)
        b = step(3, "키워드", "쓰고 싶은 분야의 키워드를 한 줄에 하나씩. 개수 제한 없음")
        self._field(b, "keywords", "lines").pack(fill="x")
        b = step(4, "네이버 로그인과 발행 방식", "브라우저 창이 열리면 직접 로그인하세요 (한 번만). 처음에는 임시저장을 권해요.")
        row = tk.Frame(b, bg=C["card"])
        row.pack(fill="x")
        Btn(row, "네이버 로그인 하기", self.on_login, kind="soft").pack(side="left")
        self.setup_login = tk.Label(row, text=f"로그인 {self.login_state}", bg=C["card"], fg=C["muted"], font=F(9))
        self.setup_login.pack(side="left", padx=12)
        mode = tk.StringVar(value=self.cfg.publish_mode)
        self.vars["publish_mode"] = mode
        for val, txt in (("draft", "임시저장 (권장)"), ("publish", "바로 발행")):
            tk.Radiobutton(row, text=txt, value=val, variable=mode, bg=C["card"], font=F(10),
                           activebackground=C["card"]).pack(side="right", padx=6)
        auto = tk.BooleanVar(value=self.cfg.auto_start)
        self.vars["auto_start"] = auto
        tk.Checkbutton(b, text="프로그램을 켜면 자동 등록 바로 시작", variable=auto, bg=C["card"], font=F(10),
                       activebackground=C["card"]).pack(anchor="w", pady=(12, 0))

        foot = tk.Frame(wrap, bg=C["bg"])
        foot.pack(fill="x", pady=6)
        Btn(foot, "설정 완료하고 시작하기", self.finish_setup, size=11, padx=26, pady=12).pack(side="right")

    def finish_setup(self):
        values = self._collect()
        key = self.setup_key.get().strip()
        if not key:
            messagebox.showwarning("설정 필요", "AI API 키를 입력하세요.")
            return
        values["gemini_api_key" if values.get("ai_provider") == "gemini" else "anthropic_api_key"] = key
        if not str(values.get("naver_blog_id", "")).strip():
            messagebox.showwarning("설정 필요", "네이버 블로그 ID를 입력하세요.")
            return
        self.cfg.update(values)
        self.cfg.setup_done = True
        self.cfg.save()
        self._refresh_side()
        self.show("home")
        self.msgs.put("설정을 저장했어요. 오른쪽 아래 '자동 등록 시작'을 누르세요.")

    # ------------------------------------------------------------ 동작
    def on_save(self):
        try:
            self.cfg.update(self._collect())
            if "remote_token" in self.vars:
                self.cfg.remote_token = self.vars["remote_token"].get()
            self.cfg.save()
        except ValueError as e:
            messagebox.showerror("저장 실패", f"숫자 칸을 확인하세요: {e}")
            return
        self.remote.stop()
        self.remote = RemoteControl(self.cfg, self.runner, self.msgs.put)
        self.remote.start()
        self._refresh_side()
        self.show(self.current)          # 안전장치로 조정된 값을 다시 보여줌
        self.msgs.put("설정을 저장했어요.")

    def _ready(self) -> bool:
        if not (self.cfg.setup_done and self.cfg.ai_key() and self.cfg.naver_blog_id):
            self.show_setup()
            return False
        return True

    def on_toggle(self):
        if self.runner.running:
            self.runner.stop()
            self.msgs.put("멈춤 요청: 지금 하던 글까지만 마치고 멈춰요.")
        elif self._ready():
            self.runner.start()
        self._refresh_home()

    def on_once(self):
        if self._ready() and not self.runner.running:
            threading.Thread(target=self.runner.run_once, daemon=True).start()

    def on_login(self):
        if "naver_blog_id" in self.vars:
            self.cfg.naver_blog_id = self.vars["naver_blog_id"].get().strip()

        def job():
            from .naver import NaverBlog
            self.msgs.put("브라우저에서 네이버에 로그인하세요 (최대 5분 대기).")
            try:
                with NaverBlog(self.cfg.naver_blog_id, self.cfg.browser_channel) as nb:
                    ok = nb.is_logged_in() or nb.login_interactive()
            except Exception as e:
                self.msgs.put(f"브라우저 실행 실패: {e}")
                ok = False
            self.login_state = "됨" if ok else "필요"
            self.msgs.put("네이버 로그인 확인됨." if ok else "네이버 로그인 확인 실패.")
        threading.Thread(target=job, daemon=True).start()

    def on_shortcut(self):
        try:
            path = install.install_and_shortcut()
            self.msgs.put(f"바탕화면에 MYDAF 아이콘을 만들었어요: {path}")
        except Exception as e:
            messagebox.showerror("아이콘 만들기 실패", str(e))

    def on_open_folder(self):
        self._open_path(app_dir())

    def _open_path(self, path: Path):
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(path)])

    # ------------------------------------------------------------ 로그 표시
    def _render_log(self, widget, lines):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if not lines:
            widget.insert("end", "진행 내용이 여기에 실시간으로 표시돼요.", "muted")
        for line in lines:
            widget.insert("end", line + "\n")
        widget.see("end")
        widget.configure(state="disabled")

    def _pump(self):
        new = []
        while not self.msgs.empty():
            new.append(f"{datetime.now():%H:%M}  {self.msgs.get()}")
        if new:
            self.log_lines = (self.log_lines + new)[-1000:]
            for name in ("home_log", "hist_log"):
                w = getattr(self, name, None)
                if w is not None and w.winfo_exists():
                    self._render_log(w, self.log_lines[-40 if name == "home_log" else -300:])
            if getattr(self, "setup_login", None) is not None and self.setup_login.winfo_exists():
                self.setup_login.configure(text=f"로그인 {self.login_state}")
            self._refresh_side()
        if self.runner.ai_problem and self.runner.ai_problem != getattr(self, "_ai_problem_shown", ""):
            self._ai_problem_shown = self.runner.ai_problem
            messagebox.showwarning("MYDAF · AI 키 확인 필요", self.runner.ai_problem +
                                   "\n\n자동 등록은 멈춰 두었어요. 키를 고친 뒤 다시 시작해 주세요.")
        self._refresh_home()
        self._refresh_job_area()
        self._refresh_job_box()
        self._refresh_header()
        self._refresh_side()
        self.root.after(700, self._pump)

    def run(self):
        self.root.mainloop()


_INSTANCE_LOCK = None


def single_instance(port: int = 47613) -> bool:
    """MYDAF 가 이미 켜져 있으면 False. 두 개가 동시에 돌면 하루 한도·간격이 꼬일 수 있다."""
    global _INSTANCE_LOCK
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
    except OSError:
        s.close()
        return False
    _INSTANCE_LOCK = s
    return True


def main():
    if not single_instance():
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("MYDAF", "MYDAF 가 이미 실행 중이에요.\n작업 표시줄에서 열려 있는 창을 확인해 주세요.")
        root.destroy()
        return
    App().run()
