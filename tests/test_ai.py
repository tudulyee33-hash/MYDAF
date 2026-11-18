import json
from types import SimpleNamespace

import anthropic

from mydaf import ai
from mydaf.sources import Source


class FakeStream:
    def __init__(self, payload, calls, kwargs):
        self.payload, self.calls, self.kwargs = payload, calls, kwargs
    def __enter__(self):
        self.calls.append(self.kwargs)
        return self
    def __exit__(self, *a): pass
    def get_final_message(self):
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def test_claude_writer_builds_structured_request(monkeypatch):
    w = ai.ClaudeWriter("sk-test")
    calls = []
    monkeypatch.setattr(w.client.beta.messages, "stream",
                        lambda **kw: FakeStream({"facts": [], "conflicts": []}, calls, kw))
    out = w.extract_facts("주제", [Source("news", "t", "https://a.com", text="본문", id="S1")])
    assert out == {"facts": [], "conflicts": []}
    kw = calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["effort"] == "high"
    assert '<source id="S1"' in kw["messages"][0]["content"]


def test_refusal_raises(monkeypatch):
    w = ai.ClaudeWriter("sk-test")
    msg = SimpleNamespace(stop_reason="refusal", content=[])
    class S(FakeStream):
        def get_final_message(self): return msg
    monkeypatch.setattr(w.client.beta.messages, "stream", lambda **kw: S(None, [], kw))
    try:
        w.write_post("주제", [])
    except RuntimeError as e:
        assert "거절" in str(e)
    else:
        raise AssertionError


def test_gemini_schema_conversion():
    g = ai.to_gemini_schema(ai.POST_SCHEMA)
    assert g["type"] == "OBJECT" and "additionalProperties" not in g
    sec = g["properties"]["sections"]["items"]
    assert sec["type"] == "OBJECT" and sec["propertyOrdering"][:2] == ["heading", "image_query"]
    assert sec["properties"]["paragraphs"]["items"]["properties"]["is_inference"]["type"] == "BOOLEAN"


class FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload
        self.text = json.dumps(payload)
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(self.status_code)


def test_gemini_writer_retries_on_rate_limit(monkeypatch):
    sleeps, calls = [], []
    monkeypatch.setattr(ai.time, "sleep", lambda s: sleeps.append(s))
    ok = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": "생각 중", "thought": True}, {"text": json.dumps({"facts": [], "conflicts": []})}]}}]}
    limited = {"error": {"code": 429, "details": [{"retryDelay": "7s"}]}}
    responses = [FakeResp(429, limited), FakeResp(200, ok)]

    def post(url, json=None, timeout=None, headers=None):
        calls.append((url, json, headers))
        return responses.pop(0)
    monkeypatch.setattr(ai.requests, "post", post)
    w = ai.GeminiWriter("gm-key", "gemini-2.5-flash")
    out = w.extract_facts("주제", [Source("news", "t", "https://a.com", text="가" * 9000, id="S1")])
    assert out == {"facts": [], "conflicts": []}
    assert len(calls) == 2 and 9 in sleeps                       # retryDelay 7초 + 여유 2초
    url, body, headers = calls[0]
    assert "models/gemini-2.5-flash:generateContent" in url and headers["x-goog-api-key"] == "gm-key"
    assert "gm-key" not in url                                     # 키는 주소에 넣지 않음
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["contents"][0]["parts"][0]["text"].count("가") == 4000   # 무료 한도용 자료 축소


def test_make_writer_picks_provider():
    from mydaf.config import Config
    assert isinstance(ai.make_writer(Config(ai_provider="gemini", gemini_api_key="k")), ai.GeminiWriter)
    assert isinstance(ai.make_writer(Config(ai_provider="claude", anthropic_api_key="k")), ai.ClaudeWriter)
    try:
        ai.make_writer(Config(ai_provider="gemini", gemini_api_key=""))
    except ValueError as e:
        assert "Gemini" in str(e)


def test_gemini_unknown_model_falls_back(monkeypatch):
    import mydaf.ai as ai
    calls = []

    class R:
        def __init__(self, code, body):
            self.status_code, self._b, self.text = code, body, "x"
        def json(self):
            return self._b
        def raise_for_status(self):
            pass

    def post(url, **kw):
        calls.append(url)
        if "gemini-2.5-flash:" in url:
            return R(200, {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}]})
        return R(404, {"error": {"message": "not found"}})

    monkeypatch.setattr(ai.requests, "post", post)
    monkeypatch.setattr(ai.GeminiWriter, "MIN_GAP_SECONDS", 0)
    w = ai.GeminiWriter("k", model="gemini-3.1-pro")
    assert w._json("s", "u", {"type": "object", "properties": {"ok": {"type": "boolean"}}}) == {"ok": True}
    assert [u.split("/models/")[1].split(":")[0] for u in calls] == ["gemini-3.1-pro", "gemini-3.1-pro-preview", "gemini-2.5-flash"]
