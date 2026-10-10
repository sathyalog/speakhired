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
from speakhired.llm import GrokLLM, LLMUnavailable, ModeStore, RoutingLLM, llm_errors  # noqa: E402
from test_ats import GOOD, REMOTE, FakeLLM, SpyLev, docx_bytes  # noqa: E402

PII_PROMPT = "Priya Sharma\nmail priya@x.com, phone +91 98765 43210\nPriya built Kafka services."
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}


class RecordingProvider:
    def __init__(self, reply=None):
        self.seen, self.reply = [], reply or {"summary": "[NAME_1] built Kafka services; contact [EMAIL_1]"}

    async def chat_json(self, system, user, schema, temperature=0.2):
        self.seen.append((system, user))
        return self.reply

    async def chat_text(self, system, user, temperature=0.6):
        self.seen.append((system, user))
        return "Hello [NAME_1]"

    async def health(self):
        return {"ok": True}


def router(mode, ollama=None, grok=None):
    store = ModeStore(path=Path(tempfile.mkdtemp()) / "mode.json")
    store.set(mode)
    return RoutingLLM(store, ollama or RecordingProvider(), grok or GrokLLM(Settings(external_api_key="k")))


async def test_offline_mode_uses_ollama_and_no_personal_details_reach_it():
    ollama, grok = RecordingProvider(), RecordingProvider()
    llm = router("offline", ollama, grok)
    out = await llm.chat_json("You review resumes for Priya Sharma.", PII_PROMPT, SCHEMA)
    assert len(ollama.seen) == 1 and grok.seen == []
    seen = " ".join(ollama.seen[0])
    for secret in ("Priya", "priya@x.com", "98765"):
        assert secret not in seen
    assert "[NAME_1]" in seen and "Kafka" in seen
    assert out["summary"] == "Priya Sharma built Kafka services; contact priya@x.com"  # answer comes back with the real details


async def test_online_mode_uses_grok_only_with_the_same_protection():
    ollama, grok = RecordingProvider(), RecordingProvider()
    llm = router("online", ollama, grok)
    assert await llm.chat_text("sys", PII_PROMPT) == "Hello Priya Sharma"
    assert ollama.seen == [] and len(grok.seen) == 1 and "priya@x.com" not in " ".join(grok.seen[0])


def settle_grok(monkeypatch, status=200, body=None, raises=None, captured=None):
    async def fake_post(self, url, **kw):
        if captured is not None:
            captured.append((str(url), kw))
        if raises:
            raise raises

        class R:
            status_code = status

            def json(self):
                return body or {"choices": [{"message": {"content": json.dumps({"summary": "ok"})}}]}
        return R()
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


async def test_grok_request_shape_and_redaction(monkeypatch):
    sent = []
    settle_grok(monkeypatch, captured=sent)
    llm = router("online", grok=GrokLLM(Settings(external_api_key="secret-key", external_model="grok-4.7")))
    assert (await llm.chat_json("sys", PII_PROMPT, SCHEMA))["summary"] == "ok"
    url, kw = sent[0]
    assert url.endswith("/chat/completions") and kw["headers"]["Authorization"] == "Bearer secret-key"
    body = kw["json"]
    assert body["model"] == "grok-4.7" and body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"] is True
    assert "priya@x.com" not in json.dumps(body) and "Priya" not in json.dumps(body)


@pytest.mark.parametrize("kwargs, code", [
    ({"status": 401}, "grok_auth"), ({"status": 403}, "grok_auth"), ({"status": 429}, "grok_rate"), ({"status": 500}, "grok_error"),
    ({"raises": httpx.ConnectError("down")}, "grok_unreachable"),
])
async def test_grok_failures_have_clear_codes(monkeypatch, kwargs, code):
    settle_grok(monkeypatch, **kwargs)
    bucket = []
    token = llm_errors.set(bucket)
    try:
        with pytest.raises(LLMUnavailable) as e:
            await router("online", grok=GrokLLM(Settings(external_api_key="k"))).chat_text("s", "hello")
    finally:
        llm_errors.reset(token)
    assert e.value.code == code and bucket and bucket[0][0] == code


async def test_missing_key_is_reported_and_never_falls_back_to_ollama():
    ollama = RecordingProvider()
    with pytest.raises(LLMUnavailable) as e:
        await router("online", ollama=ollama, grok=GrokLLM(Settings(external_api_key=""))).chat_json("s", "u", SCHEMA)
    assert e.value.code == "grok_not_configured" and "not configured" in e.value.message and ollama.seen == []


def test_mode_is_remembered_between_runs():
    path = Path(tempfile.mkdtemp()) / "mode.json"
    a = ModeStore(path=path)
    assert a.mode == "offline"
    a.set("online")
    assert ModeStore(path=path).mode == "online"
    with pytest.raises(ValueError):
        a.set("sideways")


@pytest.fixture
def client():
    main.mode_store = ModeStore(path=Path(tempfile.mkdtemp()) / "mode.json")
    main.grok = GrokLLM(Settings(external_api_key=""))
    main.llm = RoutingLLM(main.mode_store, FakeLLM(), main.grok)
    main.lev = SpyLev(Settings(lev_mode="off"))
    return TestClient(main.app)


def test_mode_endpoints(client):
    first = client.get("/api/mode").json()
    assert first["mode"] == "offline" and first["grok"]["configured"] is False
    assert client.post("/api/mode", json={"mode": "online"}).json()["mode"] == "online" and client.get("/api/mode").json()["mode"] == "online"
    assert client.post("/api/mode", json={"mode": "nope"}).status_code == 400
    assert client.get("/api/health").json()["mode"] == "online"


def test_online_without_a_key_tells_the_browser(client):
    client.post("/api/mode", json={"mode": "online"})
    # ATS carries on with rules only, but the response says why so the UI can show a notice
    r = client.post("/api/ats/analyze", files={"resume": ("cv.docx", docx_bytes(GOOD), "application/octet-stream")})
    assert r.status_code == 200 and r.json()["judge"] == "rules only" and r.headers["X-LLM-Error"] == "grok_not_configured"
    assert "not configured" in r.headers["X-LLM-Error-Message"]
    # features that need the AI to continue fail clearly
    r = client.post("/api/quick/sessions", json={"questions": [{"text": "What is Kafka?"}], "voice": "bm_george"})
    assert r.status_code == 503 and r.json()["code"] == "grok_not_configured" and "Grok key is not configured" in r.json()["detail"]
    client.post("/api/mode", json={"mode": "offline"})
    assert "X-LLM-Error" not in client.post("/api/ats/analyze", files={"resume": ("cv.docx", docx_bytes(GOOD), "application/octet-stream")}).headers


def test_online_mode_allows_the_remote_lev_server_with_redaction(client):
    main.lev = SpyLev(REMOTE)
    client.post("/api/mode", json={"mode": "offline"})
    client.post("/api/ats/analyze", files={"resume": ("cv.docx", docx_bytes(GOOD), "application/octet-stream")})
    assert main.lev.states == []  # offline: remote LEV still needs the per-run switch
    client.post("/api/mode", json={"mode": "online"})
    r = client.post("/api/ats/analyze", files={"resume": ("cv.docx", docx_bytes(GOOD), "application/octet-stream")})
    assert len(main.lev.states) == 1 and "priya.sharma@example.com" not in main.lev.states[0] and "Priya Sharma" not in main.lev.states[0]
    assert r.json()["redactions"] and any("Personal details were removed" in n for n in r.json()["notes"])


def test_ats_report_lists_what_was_removed_but_never_the_values(client):
    r = client.post("/api/ats/analyze", files={"resume": ("cv.docx", docx_bytes(GOOD), "application/octet-stream")}).json()
    assert {"name", "email", "phone number", "link"} <= set(r["redactions"])
    assert "priya.sharma@example.com" not in json.dumps(r["redactions"]) and "Priya" not in " ".join(r["notes"])
