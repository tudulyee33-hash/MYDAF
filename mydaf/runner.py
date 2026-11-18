"""원클릭 연속 실행: 주제 → 수집 → 검증 → 작성 → 자체 검토 → 원고 검사 → 발행 → 기록 → 대기 → 반복.

안전장치 (어떤 경로로 실행해도 똑같이 적용: 연속 실행, '한 편만 실행', 원격 명령)
- 하루 최대 3개 (config.HARD_DAILY_MAX). 네이버 에디터까지 간 시도는 실패해도 1개로 센다.
- 직전 글로부터 최소 3시간 (config.MIN_INTERVAL_FLOOR) + 설정한 랜덤 간격
- 활동 시간대(기본 08~22시) 밖에서는 올리지 않음
"""
from __future__ import annotations

import random
import threading
from datetime import date, datetime, timedelta
from typing import Callable

from . import ai, render, sources, topics, verify
from .config import Config
from .logs import add_history, log, post_folder, read_history, record_reasoning, save_json

# 네이버 에디터까지 도달한 시도 = 하루 한도에 포함
COUNTED = {"published", "draft", "unknown", "draft_failed", "naver_error"}
POST_LOCK = threading.Lock()          # 동시에 두 편이 올라가지 않게


class Runner:
    def __init__(self, cfg: Config, say: Callable[[str], None] = print):
        self.cfg = cfg
        self._say = say
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.state = "idle"          # idle | running | waiting | stopping
        self.last_result: dict = {}
        self.next_gap_minutes: int | None = None

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
        ok, reason, _ = self.gate()
        return {"state": self.state if self.running else "idle", "today": self.posted_today(),
                "daily_limit": self.cfg.daily_limit, "can_post_now": ok, "reason": reason,
                "last": self.last_result}

    # ------------------------------------------------------------ 안전장치
    def _attempts(self) -> list[datetime]:
        out = []
        for h in read_history():
            if h.get("status") in COUNTED:
                try:
                    out.append(datetime.fromisoformat(h["time"]))
                except (KeyError, ValueError):
                    pass
        return sorted(out)

    def posted_today(self) -> int:
        today = date.today()
        return sum(1 for t in self._attempts() if t.date() == today)

    def gate(self, now: datetime | None = None) -> tuple[bool, str, float]:
        """지금 올려도 되는지. (가능 여부, 이유, 기다릴 초)"""
        self.cfg.clamp()
        now = now or datetime.now()
        attempts = self._attempts()
        today = [t for t in attempts if t.date() == now.date()]
        if len(today) >= self.cfg.daily_limit:
            tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
            start = tomorrow.replace(hour=self.cfg.active_start_hour)
            return False, f"오늘 한도 {self.cfg.daily_limit}개 도달", (start - now).total_seconds()
        if attempts:
            gap = self.next_gap_minutes or self.cfg.interval_min_minutes
            ready_at = attempts[-1] + timedelta(minutes=gap)
            if now < ready_at:
                return False, f"직전 글 후 {gap}분 간격 대기 ({ready_at:%H:%M} 이후)", (ready_at - now).total_seconds()
        if not (self.cfg.active_start_hour <= now.hour < self.cfg.active_end_hour):
            start = now.replace(hour=self.cfg.active_start_hour, minute=0, second=0, microsecond=0)
            if now.hour >= self.cfg.active_end_hour:
                start += timedelta(days=1)
            return False, f"활동 시간({self.cfg.active_start_hour}~{self.cfg.active_end_hour}시) 밖", (start - now).total_seconds()
        return True, "", 0

    # ------------------------------------------------------------ 반복
    def _loop(self):
        self.state = "running"
        self.say(f"▶ 연속 실행 시작 (하루 최대 {self.cfg.daily_limit}개, 간격 "
                 f"{self.cfg.interval_min_minutes}~{self.cfg.interval_max_minutes}분)")
        try:
            while not self._stop.is_set():
                ok, reason, wait = self.gate()
                if not ok:
                    self.state = "waiting"
                    self.say(f"대기: {reason}")
                    self._stop.wait(min(max(wait, 30), 3600))   # 최대 1시간마다 다시 확인
                    self.state = "running"
                    continue
                result = self.run_once()
                if result.get("status") not in COUNTED and not self._stop.is_set():
                    self._stop.wait(1800)     # 쓸 만한 주제가 없으면 30분 뒤 다시
        finally:
            self.state = "idle"
            self.say("■ 연속 실행 정지")

    # ------------------------------------------------------------ 한 편
    def run_once(self, topic: str | None = None) -> dict:
        ok, reason, _ = self.gate()
        if not ok:
            self.say(f"지금은 올릴 수 없음: {reason}")
            return {"status": "blocked", "reason": reason}
        cfg = self.cfg
        writer = ai.make_writer(cfg)
        candidates = [topic] if topic else topics.next_topics(cfg)
        if not candidates:
            self.say("쓸 주제가 없습니다. 키워드를 추가하거나 구글 트렌드를 켜세요.")
            return {"status": "no_topic"}

        for t in candidates[:5]:          # 품질 기준을 못 넘으면 다음 주제로
            if self._stop.is_set() and self.running:
                break
            result = self._one(t, writer)
            self.last_result = result
            if result["status"] in COUNTED or result["status"] == "blocked":
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
            draft = writer.write_post(topic, checked["usable"])
            save_json(folder, "3a_draft.json", draft)
            self.say(f"[{topic}] 자체 검토·수정")
            post = writer.revise_post(topic, checked["usable"], draft)
            review = verify.check_draft(post, checked["usable"])
            cited = verify.cited_sources(post, checked["usable"], srcs)
            record_reasoning(post_id, topic, review["inferences"])       # 추론·추리 기록 (필수)
            save_json(folder, "3_post.json", post)
            save_json(folder, "4_review.json", review)
            if review["removed"]:
                self.say(f"[{topic}] 근거 없는 문단 {len(review['removed'])}개 제거")
            chars = verify.body_chars(post)
            if chars < cfg.min_post_chars:
                return self._skip(record, f"본문 {chars}자 (최소 {cfg.min_post_chars}자) → 품질 미달")

            blocks = render.to_blocks(post, cited, cfg.citation_align, cfg.citation_font_size)
            (folder / "preview.html").write_text(render.preview_html(post["title"], blocks, post["tags"]),
                                                 encoding="utf-8")
            return self._post(record, folder, post, blocks, checked, review, cited)
        except Exception as e:
            log.exception("작업 실패")
            return self._skip(record, f"{e.__class__.__name__}: {e}", status="error")

    def _post(self, record, folder, post, blocks, checked, review, cited) -> dict:
        cfg = self.cfg
        with POST_LOCK:
            ok, reason, _ = self.gate()          # 글 쓰는 동안 상황이 바뀌었을 수 있어 한 번 더
            if not ok:
                record.update(status="blocked", reason=reason, title=post["title"])
                add_history(record)
                self.say(f"[{record['topic']}] 원고는 저장, 발행 보류: {reason}")
                return record
            topic = record["topic"]
            self.say(f"[{topic}] 네이버 {'발행' if cfg.publish_mode == 'publish' else '임시저장'}")
            record["time"] = datetime.now().isoformat(timespec="seconds")
            from .naver import NaverBlog
            try:
                with NaverBlog(cfg.naver_blog_id, cfg.browser_channel) as nb:
                    if not nb.is_logged_in():
                        return self._skip(record, "네이버 로그인 필요 (실행 탭 → 네이버 로그인)", status="error")
                    res = nb.write(post["title"], blocks, post["tags"], cfg.publish_mode, cfg.category, folder)
            except Exception as e:
                log.exception("네이버 작성 실패")
                # 에디터까지 갔으므로 하루 한도에 포함 (중복·과다 발행 방지)
                return self._skip(record, f"네이버 작성 중 오류: {e}", status="naver_error")
            for w in res["warnings"]:
                self.say(f"  ⚠ {w}")
            record.update(status=res["status"], url=res["url"], title=post["title"],
                          facts=len(checked["usable"]), inferences=len(review["inferences"]),
                          sources=len(cited), warnings=res["warnings"])
            add_history(record)
            self.next_gap_minutes = random.randint(cfg.interval_min_minutes, cfg.interval_max_minutes)
            self.say(f"[{topic}] 완료: {post['title']} {res['url']}")
            self.say(f"오늘 {self.posted_today()}/{cfg.daily_limit}개 · 다음 글은 {self.next_gap_minutes}분 뒤 이후")
            return record

    def _skip(self, record: dict, reason: str, status: str = "skipped") -> dict:
        record.update(status=status, reason=reason)
        add_history(record)
        self.say(f"[{record['topic']}] 건너뜀: {reason}")
        return record
