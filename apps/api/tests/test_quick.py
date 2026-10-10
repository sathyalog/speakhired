import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from speakhired import main  # noqa: E402
from speakhired.config import Settings  # noqa: E402
from speakhired.engines.egress import EgressBlocked, EgressGateway, WebCheckQuery  # noqa: E402


class QuickLLM:
    async def chat_json(self, system, user, schema, temperature=0.2):
        props = schema.get("properties", {})
        if "verdict" in props:  # web-check extraction
            return {"verdict": "partial", "reference_points": ["partitions give parallelism", "offsets track progress"],
                    "missing_points": ["offsets"], "fact_flags": [{"claim": "one consumer per topic", "status": "wrong", "note": "per partition"}],
                    "sources": [{"title": "Kafka docs", "url": "https://kafka.apache.org/documentation/"}, {"title": "bad", "url": "javascript:alert(1)"}]}
        if "swaps" in props or "corrections" in props:
            return {"corrections": [{"original": "I am having", "fix": "I have", "reason": "stative verb"},
                                    {"original": "never said", "fix": "x", "reason": "y"}],
                    "swaps": [{"instead_of": "very good thing", "say": "a robust approach", "why": "more precise"},
                              {"instead_of": "not in transcript", "say": "x", "why": "y"}],
                    "impressive": {"answer_first": "A consumer group shares partitions.", "example": "In our orders service...",
                                   "trade_off": "More consumers than partitions sit idle.", "close": "So I size partitions first."},
                    "missing_outline": ["offsets"], "vocabulary_tips": [], "spoken_summary": "Good start."}
        if "scores" in props:
            return {"scores": {k: 3 for k in ["relevance", "correctness", "depth", "structure", "specificity"]}, "evidence": {},
                    "covered_points": [], "missed_points": ["offsets"], "answered": True, "next_action": "next_question"}
        return {"key_points": ["a", "b"], "follow_up": ""}

    async def chat_text(self, system, user, temperature=0.6):
        return "ok"


class Recorder:
    calls: list = []


@pytest.fixture
def client(monkeypatch):
    main.llm = QuickLLM()
    main.egress = EgressGateway(Settings(external_api_key="k", data_dir=Path(tempfile.mkdtemp())))
    Recorder.calls = []

    async def fake_post(self, url, **kw):
        Recorder.calls.append((str(url), kw.get("json")))

        class R:
            def raise_for_status(self): ...
            def json(self): return {"choices": [{"message": {"content": "Strong answers mention partitions and offsets."}}]}
        return R()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return TestClient(main.app)


def test_query_redacts_pii_and_truncates():
    q = WebCheckQuery(question="Mail me at a@b.com about https://x.io/q or +91 98765 43210?", answer="x" * 3000)
    assert "a@b.com" not in q.question and "x.io" not in q.question and "98765" not in q.question
    assert len(q.answer) == 1500
    with pytest.raises(ValueError):
        WebCheckQuery(question="   ")


def test_prompt_contains_answer_only_when_given():
    g = EgressGateway(Settings(external_api_key="k"))
    assert "Candidate answer: I use Kafka" in g.build_check_prompt(WebCheckQuery(question="What is Kafka?", answer="I use Kafka"))
    assert "No candidate answer" in g.build_check_prompt(WebCheckQuery(question="What is Kafka?"))


async def test_web_check_needs_consent_and_key():
    with pytest.raises(EgressBlocked):
        await EgressGateway(Settings(external_api_key="k")).web_check(WebCheckQuery(question="q?"), False, QuickLLM())
    with pytest.raises(EgressBlocked):
        await EgressGateway(Settings(external_api_key="")).web_check(WebCheckQuery(question="q?"), True, QuickLLM())


def _create(client, **over):
    body = {"questions": [{"text": "What is a Kafka consumer group?", "hint": "partitions shared"}], "voice": "bm_george",
            "web_check": True, "include_answer": False}
    body.update(over)
    return client.post("/api/quick/sessions", json=body)


def test_limits_and_validation(client):
    assert _create(client, questions=[]).status_code == 400
    assert _create(client, questions=[{"text": "x" * 401}]).status_code == 400
    assert _create(client, voice="nope").status_code == 400
    r = _create(client, questions=[{"text": f"Question number {i}?"} for i in range(6)])
    assert r.json()["total"] == 3


def test_preview_makes_no_network_call(client):
    r = client.post("/api/quick/preview", json={"question": "What is Kafka?", "answer": "mail me a@b.com", "include_answer": True})
    assert r.status_code == 200 and "a@b.com" not in r.json()["prompt"] and Recorder.calls == []


def test_flow_question_only_keeps_answer_local(client):
    sid = _create(client).json()["id"]
    r = client.post(f"/api/sessions/{sid}/answer", json={"transcript": "I am having very good thing with CANARY-ANSWER", "duration": 6})
    assert r.status_code == 200, r.text
    outbound = json.dumps(Recorder.calls)
    assert "CANARY-ANSWER" not in outbound and "partitions shared" not in outbound and "Kafka consumer group" in outbound
    fb = r.json()["feedback"]
    assert fb["web_check"]["verdict"] == "partial" and fb["web_check"]["answer_included"] is False
    assert [s["url"] for s in fb["web_check"]["sources"]] == ["https://kafka.apache.org/documentation/"]  # javascript: dropped
    assert [c["original"] for c in fb["corrections"]] == ["I am having"] and fb["corrected_answer"].startswith("I have")
    assert fb["impressive"] is None and r.json()["polish_pending"] is True and r.json()["done"] is True   # the slower part is requested separately
    p = client.post(f"/api/sessions/{sid}/polish/{r.json()['answer_index']}").json()
    assert [x["instead_of"] for x in p["swaps"]] == ["very good thing"]  # swap not in transcript dropped
    assert p["impressive"]["close"] and p["better_version"].startswith("A consumer group shares partitions.")


def test_flow_with_answer_sends_redacted_answer_and_hint(client):
    sid = _create(client, include_answer=True).json()["id"]
    client.post(f"/api/sessions/{sid}/answer", json={"transcript": "I am having this. Mail priya@x.com", "duration": 5})
    outbound = json.dumps(Recorder.calls)
    assert "I am having this" in outbound and "priya@x.com" not in outbound and "partitions shared" in outbound
    assert Recorder.calls and all("resume" not in json.dumps(c).lower() for c in Recorder.calls)


def test_no_web_check_stays_local(client):
    sid = _create(client, web_check=False).json()["id"]
    r = client.post(f"/api/sessions/{sid}/answer", json={"transcript": "I am having very good thing", "duration": 5})
    assert Recorder.calls == [] and r.json()["feedback"]["web_check"] is None
    assert client.post(f"/api/sessions/{sid}/polish/0").json()["impressive"]


def test_hint_returned_with_question(client):
    assert _create(client).json()["question"]["hint"] == "partitions shared"


def test_polish_is_separate_cached_and_validated(client):
    sid = _create(client, web_check=False).json()["id"]
    r = client.post(f"/api/sessions/{sid}/answer", json={"transcript": "I am having very good thing with Kafka.", "duration": 5}).json()
    assert r["feedback"]["corrected_answer"] and r["feedback"]["impressive"] is None          # fast part only
    assert client.post(f"/api/sessions/{sid}/polish/5").status_code == 404 and client.post("/api/sessions/nope/polish/0").status_code == 404
    first = client.post(f"/api/sessions/{sid}/polish/0").json()
    assert first["impressive"]["answer_first"] and first["swaps"]
    calls = []
    original = main.llm.chat_json

    async def spy(*a, **k):
        calls.append(1)
        return await original(*a, **k)
    main.llm.chat_json = spy
    assert client.post(f"/api/sessions/{sid}/polish/0").json() == first and calls == []     # second request does not call the AI again
    report = client.get(f"/api/sessions/{sid}/report").json()
    assert report["results"][0]["feedback"]["impressive"]["close"]                           # stored with the answer
