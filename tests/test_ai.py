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
