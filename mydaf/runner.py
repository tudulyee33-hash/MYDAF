"""원클릭 연속 실행: 주제 → 수집 → 검증 → 작성 → 원고 검사 → 발행 → 기록 → 대기 → 반복."""
from __future__ import annotations

import random
import threading
import time
from datetime import date, datetime
from typing import Callable

from . import ai, render, sources, topics, verify
from .config import Config
from .logs import add_history, log, post_folder, read_history, record_reasoning, save_json


class Runner:
    def __init__(self, cfg: Config, say: Callable[[str], None] = print):
        self.cfg = cfg
        self._say = say
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.state = "idle"          # idle | running | waiting | stopping
        self.last_result: dict = {}

    def say(self, msg: str):
        log.info(msg)
        self._say(msg)

    # ------------------------------------------------------------ 제어
    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        self.state = "stopping"

    def status(self) -> dict:
        return {"state": self.state if self.running else "idle", "today": self.posted_today(),
                "daily_limit": self.cfg.daily_limit, "last": self.last_result}

    def posted_today(self) -> int:
        today = date.today().isoformat()
        return sum(1 for h in read_history()
                   if h.get("time", "").startswith(today) and h.get("status") in ("published", "draft"))

    # ------------------------------------------------------------ 반복
    def _loop(self):
        self.state = "running"
        self.say("▶ 연속 실행 시작")
        try:
            while not self._stop.is_set():
                if self.posted_today() >= self.cfg.daily_limit:
                    self.say(f"오늘 한도 {self.cfg.daily_limit}개 도달. 내일까지 대기합니다.")
                    self._wait_until_tomorrow()
                    continue
                self.run_once()
                if self._stop.is_set():
                    break
                minutes = random.randint(self.cfg.interval_min_minutes, max(self.cfg.interval_min_minutes,
                                                                            self.cfg.interval_max_minutes))
                self.say(f"다음 글까지 {minutes}분 대기")
                self.state = "waiting"
                self._stop.wait(minutes * 60)
                self.state = "running"
        finally:
            self.state = "idle"
            self.say("■ 연속 실행 정지")

    def _wait_until_tomorrow(self):
        self.state = "waiting"
        while not self._stop.is_set() and self.posted_today() >= self.cfg.daily_limit:
            self._stop.wait(600)
        self.state = "running"

    # ------------------------------------------------------------ 한 편
    def run_once(self, topic: str | None = None) -> dict:
        cfg = self.cfg
        writer = ai.make_writer(cfg)
        candidates = [topic] if topic else topics.next_topics(cfg)
        if not candidates:
            self.say("쓸 주제가 없습니다. 키워드를 추가하거나 구글 트렌드를 켜세요.")
            return {"status": "no_topic"}

        for t in candidates[:5]:          # 검증 기준을 못 넘으면 다음 주제로
            if self._stop.is_set():
                break
            result = self._one(t, writer)
            self.last_result = result
            if result["status"] in ("published", "draft"):
                return result
        return self.last_result

    def _one(self, topic: str, writer) -> dict:
        cfg = self.cfg
        post_id, folder = post_folder(topic)
        record = {"time": datetime.now().isoformat(timespec="seconds"), "post_id": post_id, "topic": topic}
        try:
            self.say(f"[{topic}] 자료 수집")
            srcs = sources.collect(topic, cfg, self.say)
            save_json(folder, "1_sources.json", [s.__dict__ for s in srcs])
            if len({s.outlet for s in srcs}) < cfg.min_independent_sources:
                return self._skip(record, "독립 출처 부족")

            self.say(f"[{topic}] 사실 추출")
            extracted = writer.extract_facts(topic, srcs)
            checked = verify.verify_facts(extracted, srcs, cfg.min_independent_sources, cfg.allow_single_source)
            save_json(folder, "2_verification.json", checked)
            self.say(f"[{topic}] 검증: 통과 {len(checked['verified'])} · 단일출처 {len(checked['single'])}"
                     f" · 탈락 {len(checked['rejected'])}")
            if len(checked["usable"]) < cfg.min_verified_facts:
                return self._skip(record, f"검증된 사실 {len(checked['usable'])}개 (최소 {cfg.min_verified_facts})")

            self.say(f"[{topic}] 글 작성")
            post = writer.write_post(topic, checked["usable"])
            review = verify.check_draft(post, checked["usable"])
            cited = verify.cited_sources(post, checked["usable"], srcs)
            record_reasoning(post_id, topic, review["inferences"])       # 추론·추리 기록 (필수)
            save_json(folder, "3_post.json", post)
            save_json(folder, "4_review.json", review)
            if review["removed"]:
                self.say(f"[{topic}] 근거 없는 문단 {len(review['removed'])}개 제거")
            if not post["sections"]:
                return self._skip(record, "검사 후 남은 본문 없음")

            blocks = render.to_blocks(post, cited, cfg.citation_align, cfg.citation_font_size)
            (folder / "preview.html").write_text(render.preview_html(post["title"], blocks, post["tags"]),
                                                 encoding="utf-8")

            self.say(f"[{topic}] 네이버 {'발행' if cfg.publish_mode == 'publish' else '임시저장'}")
            from .naver import NaverBlog
            with NaverBlog(cfg.naver_blog_id, cfg.browser_channel) as nb:
                if not nb.is_logged_in():
                    return self._skip(record, "네이버 로그인 필요 (설정 → 네이버 로그인)", status="error")
                res = nb.write(post["title"], blocks, post["tags"], cfg.publish_mode, cfg.category, folder)
            for w in res["warnings"]:
                self.say(f"  ⚠ {w}")
            record.update(status=res["status"], url=res["url"], title=post["title"],
                          facts=len(checked["usable"]), inferences=len(review["inferences"]),
                          sources=len(cited), warnings=res["warnings"])
            add_history(record)
            self.say(f"[{topic}] 완료: {post['title']} {res['url']}")
            return record
        except Exception as e:
            log.exception("작업 실패")
            return self._skip(record, f"{e.__class__.__name__}: {e}", status="error")

    def _skip(self, record: dict, reason: str, status: str = "skipped") -> dict:
        record.update(status=status, reason=reason)
        add_history(record)
        self.say(f"[{record['topic']}] 건너뜀: {reason}")
        return record
