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

import time

from . import ai, images, render, sources, topics, verify
from .config import Config
from .logs import add_history, log, post_folder, read_history, record_reasoning, save_json

# 네이버 에디터까지 도달한 시도 = 하루 한도에 포함
COUNTED = {"published", "draft", "unknown", "draft_failed", "naver_error"}
POST_LOCK = threading.Lock()          # 동시에 두 편이 올라가지 않게
STEPS = ["자료 수집", "사실 검증", "원고 작성", "이미지 준비", "에디터 작성", "저장 확인"]
STEP_PCT = [(0, 15), (15, 30), (30, 55), (55, 65), (65, 95), (95, 100)]
STEP_EXPECTED_SEC = [60, 90, 180, 40, 180, 10]      # 단계별 대략 걸리는 시간 (화면 진행률용)


def typical_step_seconds(history: list[dict] | None = None, n: int = 7) -> list[int]:
    """지난 글(최대 n편)의 단계별 걸린 시간 중앙값. 기록이 없으면 기본 예상치."""
    rows = [h["step_times"] for h in (history if history is not None else read_history())
            if isinstance(h.get("step_times"), list) and len(h["step_times"]) == len(STEPS)][-n:]
    if not rows:
        return list(STEP_EXPECTED_SEC)
    out = []
    for i in range(len(STEPS)):
        vals = sorted(r[i] for r in rows if r[i])
        out.append(int(vals[len(vals) // 2]) if vals else STEP_EXPECTED_SEC[i])
    return out


def remaining_seconds(job: dict | None, typical: list[int], now: float | None = None) -> int:
    """남은 시간 추정: 지금 단계의 남은 몫 + 아직 안 한 단계들의 보통 시간."""
    if not job or job.get("done"):
        return 0
    now = now or time.time()
    idx = job.get("step", 0)
    in_step = now - job.get("step_started", job.get("started", now))
    left = max(typical[idx] - in_step, typical[idx] * 0.1)
    return int(left + sum(typical[idx + 1:]))


def display_pct(job: dict | None, now: float | None = None) -> int:
    """화면에 보여줄 진행률. AI 작성처럼 오래 걸리는 단계에서도 숫자가 멈춰 보이지 않게
    단계 안에서 예상 시간에 맞춰 조금씩 올리되, 다음 단계 시작점은 넘지 않는다."""
    if not job:
        return 0
    if job.get("done"):
        return 100 if job.get("pct", 0) >= 95 else job.get("pct", 0)
    idx = job.get("step", 0)
    lo, hi = STEP_PCT[idx]
    started = job.get("step_started", job.get("started", now or time.time()))
    elapsed = max(0.0, (now or time.time()) - started)
    creep = lo + (hi - lo) * min(0.9, elapsed / STEP_EXPECTED_SEC[idx])
    return int(min(max(job.get("pct", 0), creep), max(hi - 1, lo) if job.get("pct", 0) < hi else hi))


def _block_summary(b: dict) -> dict:
    if b["type"] == "image":
        return {"type": "image"}
    if b["type"] == "citations":
        return {"type": "citations", "text": "출처 " + str(len(b.get("lines", []))) + "건"}
    return {"type": b["type"], "text": b.get("text", "")[:160]}


class Runner:
    def __init__(self, cfg: Config, say: Callable[[str], None] = print):
        self.cfg = cfg
        self._say = say
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.state = "idle"          # idle | running | waiting | stopping
        self.last_result: dict = {}
        self.next_gap_minutes: int | None = None
        self.job: dict | None = None      # 화면에 보여줄 현재 작업 진행 상황
        self.ai_problem = ""              # AI 키·결제 문제 (화면 알림용)
        self.finish_mode: str | None = None   # 이번 작업만 '다 쓰면' 바꾸기 (draft | publish)

    def step(self, idx: int, frac: float = 0.0, msg: str = ""):
        """진행 단계 갱신 (화면의 단계 표시·진행률 막대용)."""
        if self.job is None:
            return
        lo, hi = STEP_PCT[idx]
        now = time.time()
        prev = self.job.get("step")
        if prev != idx or "step_started" not in self.job:
            times = self.job.setdefault("step_times", [0] * len(STEPS))
            if prev is not None and "step_started" in self.job and prev < idx:
                times[prev] = int(now - self.job["step_started"])
            self.job["step_started"] = now
        pct = int(lo + (hi - lo) * max(0.0, min(frac, 1.0)))
        self.job.update(step=idx, pct=max(pct, self.job.get("pct", 0)))
        if msg:
            self.job["events"].append((datetime.now().strftime("%H:%M:%S"), msg))
            self.job["events"] = self.job["events"][-50:]

    def say(self, msg: str):
        log.info(msg)
        self._say(msg)
        if self.job and not self.job.get("done"):
            self.job["events"].append((datetime.now().strftime("%H:%M:%S"), msg.strip()))
            self.job["events"] = self.job["events"][-50:]

    # ------------------------------------------------------------ 제어
    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self.ai_problem = ""
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def start_batch(self, topic: str | None, count: int, mode: str | None = None) -> bool:
        """'새 글 쓰기': 주제(없으면 자동) n편. 2편째부터는 안전 간격을 지켜 이어서 쓴다."""
        if self.running:
            return False
        self._stop.clear()
        self.ai_problem = ""
        self.thread = threading.Thread(target=self._batch, args=(topic, max(1, min(int(count), 3)), mode),
                                       daemon=True)
        self.thread.start()
        return True

    def _batch(self, topic, count, mode):
        self.state = "running"
        self.finish_mode = mode if mode in ("draft", "publish") else None
        done = 0
        try:
            self.say(f"▶ 새 글 쓰기 {count}편" + (f" · {topic}" if topic else " · 주제는 자동으로"))
            while done < count and not self._stop.is_set():
                ok, reason, wait = self.gate()
                if not ok:
                    if done == 0 and "한도" in reason:
                        self.say(f"지금은 쓸 수 없어요: {reason}")
                        break
                    at = datetime.now() + timedelta(seconds=wait)
                    self.state = "waiting"
                    self.say(f"{done + 1}번째 글은 {at:%m/%d %H:%M}에 이어서 써요 ({reason})")
                    self._stop.wait(min(max(wait, 30), 3600))
                    self.state = "running"
                    continue
                res = self.run_once(topic if done == 0 else None)
                if res.get("status") == "ai_error" or res.get("status") == "no_topic":
                    break
                done += 1
        finally:
            self.finish_mode = None
            self.state = "idle"
            self.say("■ 새 글 쓰기 끝")

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
                if result.get("status") not in COUNTED and not self._stop.is_set():  # ai_error 는 위에서 stop
                    mins = 10 if result.get("status") == "ai_busy" else 30
                    retry = datetime.now() + timedelta(minutes=mins)
                    self.state = "waiting"
                    self.say(f"이번엔 기준을 넘은 주제가 없어 {retry:%H:%M}에 다시 시도해요 (사유: "
                             f"{result.get('reason') or result.get('status')})")
                    self._stop.wait(mins * 60)     # 쓸 만한 주제가 없으면 30분(AI 혼잡이면 10분) 뒤 다시
                    self.state = "running"
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
        if not topic:
            self.say("주제를 고르는 중 (키워드" + (" + 구글 트렌드)" if cfg.use_google_trends else ")"))
        candidates = [topic] if topic else topics.next_topics(cfg)
        if candidates and not topic:
            self.say("이번 후보: " + ", ".join(candidates[:5]))
        if not candidates:
            self.say("쓸 주제가 없습니다. 키워드를 추가하거나 구글 트렌드를 켜세요.")
            return {"status": "no_topic"}

        for t in candidates[:5]:          # 품질 기준을 못 넘으면 다음 주제로
            if self._stop.is_set() and self.running:
                break
            result = self._one(t, writer)
            self.last_result = result
            if result["status"] in COUNTED or result["status"] in ("blocked", "ai_error", "ai_busy"):
                return result
        return self.last_result

    def _one(self, topic: str, writer) -> dict:
        cfg = self.cfg
        post_id, folder = post_folder(topic)
        record = {"time": datetime.now().isoformat(timespec="seconds"), "post_id": post_id, "topic": topic}
        self.job = {"topic": topic, "step": 0, "pct": 0, "started": time.time(), "events": [], "done": False,
                    "post_id": post_id, "folder": str(folder), "style": cfg.writer_style,
                    "finish_mode": self.finish_mode or cfg.publish_mode, "typical": typical_step_seconds(),
                    "title": "", "outline": [], "blocks_total": 0, "blocks_done": 0,
                    "photos_total": 0, "photos_done": 0, "current": None, "blocks": []}
        try:
            result = self._one_inner(topic, writer, post_id, folder, record)
        finally:
            if self.job:
                now = time.time()
                times = self.job.setdefault("step_times", [0] * len(STEPS))
                idx = self.job.get("step", 0)
                if not times[idx] and "step_started" in self.job:
                    times[idx] = int(now - self.job["step_started"])
                self.job["elapsed"] = int(now - self.job["started"])
                self.job["done"] = True
        self.job["status"] = result.get("status")
        self.job["reason"] = result.get("reason", "")
        self.job["url"] = result.get("url", "")
        return result

    def _one_inner(self, topic, writer, post_id, folder, record) -> dict:
        cfg = self.cfg
        try:
            self.step(0, 0, "자료 수집을 시작합니다")
            self.say(f"[{topic}] 자료 수집")
            srcs = sources.collect(topic, cfg, self.say)
            save_json(folder, "1_sources.json", [s.__dict__ for s in srcs])
            if len({s.outlet for s in srcs}) < cfg.min_independent_sources:
                return self._skip(record, "독립 출처 부족")

            self.step(1, 0, f"자료 {len(srcs)}건 확보 · 사실 추출과 교차 검증 중")
            self.say(f"[{topic}] 사실 추출")
            extracted = writer.extract_facts(topic, srcs)
            checked = verify.verify_facts(extracted, srcs, cfg.min_independent_sources, cfg.allow_single_source)
            save_json(folder, "2_verification.json", checked)
            self.say(f"[{topic}] 검증: 통과 {len(checked['verified'])} · 단일출처 {len(checked['single'])}"
                     f" · 탈락 {len(checked['rejected'])}")
            if len(checked["usable"]) < cfg.min_verified_facts:
                return self._skip(record, f"검증된 사실 {len(checked['usable'])}개 (최소 {cfg.min_verified_facts})")

            self.step(2, 0, f"검증 통과 사실 {len(checked['usable'])}개 · 원고 작성 중")
            self.say(f"[{topic}] 글 작성")
            draft = writer.write_post(topic, checked["usable"])
            save_json(folder, "3a_draft.json", draft)
            self.step(2, 0.5, "편집장 검토·수정 중")
            self.say(f"[{topic}] 자체 검토·수정")
            post = writer.revise_post(topic, checked["usable"], draft)
            review = verify.check_draft(post, checked["usable"])
            cited = verify.cited_sources(post, checked["usable"], srcs)
            record_reasoning(post_id, topic, review["inferences"])       # 추론·추리 기록 (필수)
            self.job.update(title=post.get("title", ""),
                            outline=[sec.get("heading", "") for sec in post.get("sections", [])])
            self.step(2, 1, f"제목이 정해졌어요 · {post.get('title', '')}")
            save_json(folder, "3_post.json", post)
            save_json(folder, "4_review.json", review)
            if review["removed"]:
                self.say(f"[{topic}] 근거 없는 문단 {len(review['removed'])}개 제거")
            chars = verify.body_chars(post)
            self.job["chars"] = chars
            if chars < cfg.min_post_chars:
                return self._skip(record, f"본문 {chars}자 (최소 {cfg.min_post_chars}자) → 품질 미달")

            pics = []
            if cfg.use_images:
                self.step(3, 0, "이미지 준비 중 (자유 라이선스)")
                self.say(f"[{topic}] 이미지 준비")
                pics = images.prepare([s.get("image_query", "") or topic for s in post["sections"]],
                                      folder / "images", cfg, self.say)
            self.step(3, 1, f"이미지 {sum(1 for x in pics if x)}장 준비됨")
            blocks = render.to_blocks(post, cited, cfg.citation_align, cfg.citation_font_size, images=pics,
                                      heading_size=cfg.heading_font_size, body_size=cfg.body_font_size,
                                      heading_style=cfg.heading_style)
            self.job.update(blocks=[_block_summary(b) for b in blocks],
                            blocks_total=sum(1 for b in blocks if b["type"] in ("para", "heading")),
                            photos_total=sum(1 for b in blocks if b["type"] == "image"))
            (folder / "preview.html").write_text(render.preview_html(post["title"], blocks, post["tags"]),
                                                 encoding="utf-8")
            return self._post(record, folder, post, blocks, checked, review, cited)
        except ai.AIAccountError as e:
            log.error("AI 키·결제 문제: %s", e)
            self.ai_problem = str(e)
            self._stop.set()           # 다시 시도해도 같은 결과라 자동 등록을 멈춘다
            self.say(f"⚠ {e}")
            self.say("AI 키 문제가 해결될 때까지 자동 등록을 멈췄어요. 고친 뒤 다시 시작을 눌러 주세요.")
            return self._skip(record, str(e), status="ai_error")
        except ai.AIBusyError as e:
            log.warning("AI 혼잡: %s", e)
            self.say(f"⚠ {e}")
            return self._skip(record, str(e), status="ai_busy")
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
            mode = self._mode()
            self.say(f"[{topic}] 네이버 {'발행' if mode == 'publish' else '임시저장'}")
            record["time"] = datetime.now().isoformat(timespec="seconds")
            from .naver import NaverBlog
            try:
                self.step(4, 0, "네이버 편집기에 작성 중 · 창을 닫지 마세요")
                with NaverBlog(cfg.naver_blog_id, cfg.browser_channel, headless=not cfg.show_browser) as nb:
                    if not nb.is_logged_in():
                        return self._skip(record, "네이버 로그인 필요 (바로 시작 → 네이버 로그인 확인)", status="error")
                    res = nb.write(post["title"], blocks, post["tags"], self._mode, cfg.category, folder,
                                   on_progress=lambda frac, msg: self._transfer(blocks, frac))
                self.step(5, 1, "저장 확인 완료" if res["status"] in ("published", "draft") else "저장 확인 필요")
            except Exception as e:
                log.exception("네이버 작성 실패")
                # 에디터까지 갔으므로 하루 한도에 포함 (중복·과다 발행 방지)
                return self._skip(record, f"네이버 작성 중 오류: {e}", status="naver_error")
            for w in res["warnings"]:
                self.say(f"  ⚠ {w}")
            record.update(step_times=list(self.job.get("step_times", [])),
                          elapsed=int(time.time() - self.job["started"]),
                          chars=verify.body_chars(post), photos=self.job.get("photos_total", 0))
            record.update(status=res["status"], url=res["url"], title=post["title"],
                          facts=len(checked["usable"]), inferences=len(review["inferences"]),
                          sources=len(cited), warnings=res["warnings"])
            add_history(record)
            self.next_gap_minutes = random.randint(cfg.interval_min_minutes, cfg.interval_max_minutes)
            self.say(f"[{topic}] 완료: {post['title']} {res['url']}")
            self.say(f"오늘 {self.posted_today()}/{cfg.daily_limit}개 · 다음 글은 {self.next_gap_minutes}분 뒤 이후")
            return record

    def _mode(self) -> str:
        """다 쓰면 어떻게 할지. 작성 중에 화면에서 바꿀 수 있어 마지막 순간에 읽는다."""
        if self.job and self.job.get("finish_mode") in ("draft", "publish"):
            return self.job["finish_mode"]
        return self.cfg.publish_mode

    def set_finish_mode(self, mode: str) -> None:
        if mode in ("draft", "publish") and self.job and not self.job.get("done"):
            self.job["finish_mode"] = mode
            self.say("다 쓰면 " + ("바로 올려요." if mode == "publish" else "임시저장만 해 둬요."))

    def _transfer(self, blocks: list[dict], frac: float) -> None:
        """에디터로 옮기는 중: 몇 번째 블록인지 화면용으로 기록."""
        i = min(int(round(frac * len(blocks))), len(blocks))
        done = blocks[:i]
        self.job.update(blocks_done=sum(1 for b in done if b["type"] in ("para", "heading")),
                        photos_done=sum(1 for b in done if b["type"] == "image"),
                        current=i if i < len(blocks) else None)
        self.step(4, frac)

    def _skip(self, record: dict, reason: str, status: str = "skipped") -> dict:
        record.update(status=status, reason=reason)
        add_history(record)
        self.say(f"[{record['topic']}] 건너뜀: {reason}")
        return record
