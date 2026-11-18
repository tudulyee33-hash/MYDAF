"""가짜 AI·가짜 수집·가짜 네이버로 전체 흐름과 원격 제어를 확인한다 (네트워크 불필요)."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("MYDAF_HOME", tempfile.mkdtemp())

import requests  # noqa: E402

from mydaf import logs, runner as runner_mod  # noqa: E402
from mydaf.config import Config  # noqa: E402
from mydaf.remote import RemoteControl  # noqa: E402
from mydaf.sources import Source  # noqa: E402


class FakeWriter:
    def extract_facts(self, topic, sources):
        return {"facts": [
            {"statement": f"사실{i}", "evidence": [{"source_id": "S1", "quote": f"공통 문장 {i}번 내용입니다"},
                                                  {"source_id": "S2", "quote": f"공통 문장 {i}번 내용입니다"}]}
            for i in range(7)], "conflicts": []}

    def write_post(self, topic, facts):
        return {"title": f"{topic} 정리", "intro": "도입", "conclusion": "마무리", "tags": ["a", "b"],
                "sections": [{"heading": "현황", "paragraphs": [
                    {"text": "사실 문단", "fact_ids": ["F1", "F2"], "is_inference": False, "inference_reasoning": ""},
                    {"text": "추론 문단", "fact_ids": ["F3"], "is_inference": True,
                     "inference_reasoning": "F3의 증가 추세로 보아 내년에도 이어질 것으로 추정"}]}]}


    def revise_post(self, topic, facts, draft):
        draft["sections"][0]["paragraphs"][0]["text"] = "검토 후 사실 문단 " * 300
        return draft


class FakeBlog:
    written = []

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def is_logged_in(self): return True

    def write(self, title, blocks, tags, mode, category, folder, on_progress=lambda f, m: None):
        on_progress(0.5, "본문")
        FakeBlog.written.append((title, blocks, tags, mode))
        return {"status": "draft", "url": "", "warnings": []}


def fake_collect(topic, cfg, progress):
    text = " ".join(f"공통 문장 {i}번 내용입니다." for i in range(7))
    return [Source("news", "기사1", "https://a.com/1", "A", "2026-11-01", text=text, id="S1"),
            Source("news", "기사2", "https://b.com/2", "B", "2026-11-02", text=text, id="S2")]


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_history(monkeypatch, tmp_path):
    hist = tmp_path / "history.jsonl"
    monkeypatch.setattr(logs, "history_path", lambda: hist)
    return hist


ALWAYS = dict(active_start_hour=0, active_end_hour=24, use_images=False)


def test_full_pipeline_logs_reasoning(monkeypatch):
    import mydaf.naver
    monkeypatch.setattr(runner_mod.ai, "make_writer", lambda cfg: FakeWriter())
    monkeypatch.setattr(runner_mod.sources, "collect", fake_collect)
    monkeypatch.setattr(mydaf.naver, "NaverBlog", FakeBlog)
    cfg = Config(anthropic_api_key="x", naver_blog_id="me", keywords=["전기차"], use_google_trends=False, **ALWAYS)
    r = runner_mod.Runner(cfg, say=lambda m: None)
    res = r.run_once()
    assert res["status"] == "draft" and res["inferences"] == 1 and res["sources"] == 2
    assert r.job["done"] and r.job["pct"] == 100 and r.job["step"] == 5 and r.job["events"]
    title, blocks, tags, mode = FakeBlog.written[-1]
    assert title == "전기차 정리" and mode == "draft"
    assert blocks[-1]["type"] == "citations" and blocks[-1]["align"] == "right"
    rec = json.loads((logs.LOG_DIR / "reasoning.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["topic"] == "전기차" and "추정" in rec["inferences"][0]["reasoning"]
    folder = logs.POST_DIR / res["post_id"]
    assert {"1_sources.json", "2_verification.json", "3_post.json", "4_review.json", "preview.html"} <= {
        p.name for p in folder.iterdir()}
    # 방금 쓴 주제는 쿨다운 → 다음 회차 후보에서 빠짐
    assert runner_mod.topics.next_topics(cfg) == []
    # 3시간 간격 안전장치: 바로 다음 글은 막힘 (원고 작성 전에 막혀서 AI 비용도 안 씀)
    blocked = r.run_once("다른 주제")
    assert blocked["status"] == "blocked" and "간격" in blocked["reason"]


def _hist(path, times, status="published"):
    path.write_text("".join(json.dumps({"time": t.isoformat(), "topic": f"t{i}", "status": status},
                                       ensure_ascii=False) + "\n" for i, t in enumerate(times)), encoding="utf-8")


def test_daily_cap_is_hard_3(fresh_history):
    from datetime import datetime, timedelta
    cfg = Config(daily_limit=10, interval_min_minutes=5, **ALWAYS)
    assert cfg.daily_limit == 3 and cfg.interval_min_minutes == 180
    cfg.update({"daily_limit": 50, "interval_min_minutes": 1})
    assert cfg.daily_limit == 3 and cfg.interval_min_minutes == 180
    now = datetime.now().replace(hour=23, minute=0)
    r = runner_mod.Runner(cfg, say=lambda m: None)
    _hist(fresh_history, [now - timedelta(hours=h) for h in (12, 8, 4)])
    ok, reason, wait = r.gate(now)
    assert not ok and "한도 3" in reason and wait > 0
    # 실패한 네이버 시도도 한도에 포함
    _hist(fresh_history, [now - timedelta(hours=h) for h in (12, 8, 4)], status="naver_error")
    assert not r.gate(now)[0]
    # 2개만 썼고 4시간 지났으면 가능
    _hist(fresh_history, [now - timedelta(hours=h) for h in (12, 4)])
    assert r.gate(now)[0]


def test_interval_and_active_hours(fresh_history):
    from datetime import datetime, timedelta
    cfg = Config(active_start_hour=8, active_end_hour=22)
    r = runner_mod.Runner(cfg, say=lambda m: None)
    noon = datetime.now().replace(hour=12, minute=0)
    _hist(fresh_history, [noon - timedelta(minutes=100)])
    ok, reason, _ = r.gate(noon)
    assert not ok and "간격" in reason
    _hist(fresh_history, [])
    assert r.gate(noon)[0]
    ok, reason, wait = r.gate(noon.replace(hour=23))
    assert not ok and "활동 시간" in reason and 0 < wait <= 9 * 3600


def test_skips_when_sources_not_independent(monkeypatch):
    monkeypatch.setattr(runner_mod.ai, "make_writer", lambda cfg: FakeWriter())
    monkeypatch.setattr(runner_mod.sources, "collect",
                        lambda t, c, p: [Source("news", "x", "https://a.com/1", text="t", id="S1")])
    cfg = Config(anthropic_api_key="x", naver_blog_id="me", use_google_trends=False, **ALWAYS)
    res = runner_mod.Runner(cfg, say=lambda m: None).run_once("단일출처주제")
    assert res["status"] == "skipped" and "독립 출처" in res["reason"]


def test_remote_server_roundtrip():
    token = "t" * 20
    srv = subprocess.Popen([sys.executable, str(Path(__file__).parents[1] / "server/remote_server.py"),
                            "--port", "18787", "--host", "127.0.0.1"], env={**os.environ, "MYDAF_TOKEN": token, "PYTHONIOENCODING": "utf-8"})
    try:
        base = "http://127.0.0.1:18787"
        for _ in range(50):
            try:
                requests.get(base + "/", timeout=1)
                break
            except requests.ConnectionError:
                time.sleep(0.1)
        assert requests.get(base + "/api/commands?device=d", timeout=3).status_code == 401
        h = {"Authorization": "Bearer " + token}
        requests.post(base + "/api/send", headers=h, json={"device": "d", "type": "set_config",
                                                           "values": {"daily_limit": 2}}, timeout=3)
        requests.post(base + "/api/send", headers=h, json={"device": "d", "type": "format_disk"}, timeout=3)
        cmds = requests.get(base + "/api/commands?device=d", headers=h, timeout=3).json()["commands"]
        assert [c["type"] for c in cmds] == ["set_config", "format_disk"]

        cfg = Config(remote_enabled=True, remote_url=base, remote_token=token)
        rc = RemoteControl(cfg, runner_mod.Runner(cfg, say=lambda m: None), say=lambda m: None)
        assert rc.handle(cmds[0])[0] and cfg.daily_limit == 2
        ok, msg = rc.handle(cmds[1])
        assert not ok and "허용되지 않은" in msg
        rc._report(base, "d", cmds[0]["id"], True, "done")
        page = requests.get(base + "/?token=" + token, timeout=3).text
        assert "MYDAF" in page and "d" in page
    finally:
        srv.terminate()


def test_display_pct_creeps_within_step_and_never_overshoots():
    from mydaf.runner import display_pct
    t0 = 1000.0
    job = {"step": 2, "pct": 30, "started": t0, "step_started": t0, "done": False}
    assert display_pct(job, now=t0) == 30
    mid = display_pct(job, now=t0 + 90)
    assert 30 < mid < 55
    late = display_pct(job, now=t0 + 10_000)
    assert mid <= late < 55          # 다음 단계 시작 전엔 그 단계 끝을 넘지 않음
    job.update(done=True, pct=100)
    assert display_pct(job, now=t0) == 100
    assert display_pct(None) == 0


def test_ai_account_error_stops_loop_and_is_not_counted(monkeypatch):
    class Broke(FakeWriter):
        def extract_facts(self, topic, sources):
            raise runner_mod.ai.AIAccountError("Gemini 크레딧이 다 떨어졌어요.")
    monkeypatch.setattr(runner_mod.ai, "make_writer", lambda cfg: Broke())
    monkeypatch.setattr(runner_mod.sources, "collect", fake_collect)
    cfg = Config(gemini_api_key="x", keywords=["a", "b", "c"], use_google_trends=False, **ALWAYS)
    said = []
    r = runner_mod.Runner(cfg, say=said.append)
    r.start()
    r.thread.join(timeout=10)
    assert not r.running and "크레딧" in r.ai_problem
    assert r.last_result["status"] == "ai_error" and r.posted_today() == 0
    assert sum(m.startswith("⚠") for m in said) == 1    # 주제마다 반복하지 않고 한 번만
