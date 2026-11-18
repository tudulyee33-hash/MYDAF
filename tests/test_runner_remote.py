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
            for i in range(5)], "conflicts": []}

    def write_post(self, topic, facts):
        return {"title": f"{topic} 정리", "intro": "도입", "conclusion": "마무리", "tags": ["a", "b"],
                "sections": [{"heading": "현황", "paragraphs": [
                    {"text": "사실 문단", "fact_ids": ["F1", "F2"], "is_inference": False, "inference_reasoning": ""},
                    {"text": "추론 문단", "fact_ids": ["F3"], "is_inference": True,
                     "inference_reasoning": "F3의 증가 추세로 보아 내년에도 이어질 것으로 추정"}]}]}


class FakeBlog:
    written = []

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def is_logged_in(self): return True

    def write(self, title, blocks, tags, mode, category, folder):
        FakeBlog.written.append((title, blocks, tags, mode))
        return {"status": "draft", "url": "", "warnings": []}


def fake_collect(topic, cfg, progress):
    text = " ".join(f"공통 문장 {i}번 내용입니다." for i in range(5))
    return [Source("news", "기사1", "https://a.com/1", "A", "2026-11-01", text=text, id="S1"),
            Source("news", "기사2", "https://b.com/2", "B", "2026-11-02", text=text, id="S2")]


def test_full_pipeline_logs_reasoning(monkeypatch):
    import mydaf.naver
    monkeypatch.setattr(runner_mod.ai, "make_writer", lambda cfg: FakeWriter())
    monkeypatch.setattr(runner_mod.sources, "collect", fake_collect)
    monkeypatch.setattr(mydaf.naver, "NaverBlog", FakeBlog)
    cfg = Config(anthropic_api_key="x", naver_blog_id="me", keywords=["전기차"], use_google_trends=False)
    r = runner_mod.Runner(cfg, say=lambda m: None)
    res = r.run_once()
    assert res["status"] == "draft" and res["inferences"] == 1 and res["sources"] == 2
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


def test_skips_when_sources_not_independent(monkeypatch):
    monkeypatch.setattr(runner_mod.ai, "make_writer", lambda cfg: FakeWriter())
    monkeypatch.setattr(runner_mod.sources, "collect",
                        lambda t, c, p: [Source("news", "x", "https://a.com/1", text="t", id="S1")])
    cfg = Config(anthropic_api_key="x", naver_blog_id="me", use_google_trends=False)
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
