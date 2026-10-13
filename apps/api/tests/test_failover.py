import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

import httpx  # noqa: E402
import pytest  # noqa: E402

from speakhired.config import Settings  # noqa: E402
from speakhired.llm import (  # noqa: E402
    CooldownStore, LLMUnavailable, ModeStore, ProviderPool, RoutingLLM, build_online_providers, llm_switches, _next_utc_midnight,
)
from test_mode import RecordingProvider  # noqa: E402

SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}
OK = {"choices": [{"message": {"content": json.dumps({"summary": "ok"})}}]}
NOW = 1_700_000_000.0  # 14 Nov 2023, 22:13 UTC: a fixed clock so the tests do not depend on the time of day


def fake_api(monkeypatch, replies):
    """replies maps a host fragment (groq, mistral, ...) to (status, body). Returns the list of requests sent."""
    sent = []

    async def fake_post(self, url, **kw):
        sent.append((str(url), kw))
        for host, (status, body) in replies.items():
            if host in str(url):
                class R:
                    status_code = status

                    def json(self):
                        return body
                return R()
        raise AssertionError(f"unexpected request to {url}")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return sent


def limit(message):
    return (429, {"error": {"message": message}})


def pool_for(store_dir, order="groq,mistral,gemini,xai,custom", **keys):
    settings = Settings(data_dir=Path(store_dir), llm_provider_order=order, **keys)
    return ProviderPool(build_online_providers(settings), store=CooldownStore(Path(store_dir) / "llm_cooldown.json"), clock=lambda: NOW)


def online(pool, ollama=None):
    store = ModeStore(path=Path(tempfile.mkdtemp()) / "mode.json")
    store.set("online")
    return RoutingLLM(store, ollama or RecordingProvider(), pool)


def test_only_providers_with_a_key_are_used_in_order():
    providers = build_online_providers(Settings(groq_api_key="gk", mistral_api_key="mk", llm_provider_order="mistral,groq"))
    assert [p.provider for p in providers] == ["Mistral", "Groq"]
    assert build_online_providers(Settings(external_api_key="", groq_api_key="", mistral_api_key="")) == []


def test_legacy_external_key_is_used_once_even_if_a_named_slot_has_it():
    providers = build_online_providers(Settings(groq_api_key="gk", external_api_key="gk", external_api_base="https://api.groq.com/openai/v1"))
    assert len(providers) == 1 and providers[0].provider == "Groq"


async def test_switches_to_the_next_provider_when_one_hits_its_limit(monkeypatch):
    sent = fake_api(monkeypatch, {"groq.com": limit("Rate limit reached for requests per minute"), "mistral.ai": (200, OK)})
    switches = []
    token = llm_switches.set(switches)
    try:
        llm = online(pool_for(tempfile.mkdtemp(), groq_api_key="gk", mistral_api_key="mk"))
        assert await llm.chat_json("s", "u", SCHEMA) == {"summary": "ok"}
    finally:
        llm_switches.reset(token)
    assert [u.split("/")[2] for u, _ in sent] == ["api.groq.com", "api.mistral.ai"]
    assert switches == ["Groq has reached its limit. Switched to Mistral. Please wait a few seconds."]


async def test_a_per_minute_limit_pauses_briefly_and_a_daily_limit_until_utc_midnight(monkeypatch):
    fake_api(monkeypatch, {"groq.com": limit("Too many requests"), "mistral.ai": (200, OK)})
    folder = tempfile.mkdtemp()
    pool = pool_for(folder, groq_api_key="gk", mistral_api_key="mk")
    await online(pool).chat_text("s", "u")
    assert pool.until[next(k for k in pool.until if k.startswith("Groq"))] == NOW + 60

    fake_api(monkeypatch, {"groq.com": limit("You have exceeded your free tokens per day"), "mistral.ai": (200, OK)})
    pool = pool_for(tempfile.mkdtemp(), groq_api_key="gk", mistral_api_key="mk")
    await online(pool).chat_text("s", "u")
    assert pool.until[next(k for k in pool.until if k.startswith("Groq"))] == _next_utc_midnight(NOW)


async def test_a_pause_is_remembered_after_a_restart(monkeypatch):
    folder = tempfile.mkdtemp()
    fake_api(monkeypatch, {"groq.com": limit("Requests per day exceeded"), "mistral.ai": (200, OK)})
    await online(pool_for(folder, groq_api_key="gk", mistral_api_key="mk")).chat_text("s", "u")

    sent = fake_api(monkeypatch, {"groq.com": (200, OK), "mistral.ai": (200, OK)})
    await online(pool_for(folder, groq_api_key="gk", mistral_api_key="mk")).chat_text("s", "u")  # a fresh pool: a restart
    assert [u.split("/")[2] for u, _ in sent] == ["api.mistral.ai"]  # Groq stays paused until its reset time


async def test_every_provider_at_its_limit_gives_one_clear_message(monkeypatch):
    fake_api(monkeypatch, {"groq.com": limit("Too many requests"), "mistral.ai": limit("Too many requests")})
    llm = online(pool_for(tempfile.mkdtemp(), groq_api_key="gk", mistral_api_key="mk"), ollama=RecordingProvider())
    with pytest.raises(LLMUnavailable) as e:
        await llm.chat_json("s", "u", SCHEMA)
    assert e.value.code == "grok_rate" and "Every online AI service has reached its usage limit" in e.value.message and "UTC" in e.value.message


async def test_a_bad_key_does_not_switch_because_another_provider_will_not_fix_it(monkeypatch):
    sent = fake_api(monkeypatch, {"groq.com": (401, {"error": {"message": "Invalid API Key"}}), "mistral.ai": (200, OK)})
    with pytest.raises(LLMUnavailable) as e:
        await online(pool_for(tempfile.mkdtemp(), groq_api_key="gk", mistral_api_key="mk")).chat_text("s", "u")
    assert e.value.code == "grok_auth" and len(sent) == 1


async def test_no_key_still_gives_the_not_configured_message_and_never_uses_offline_model(monkeypatch):
    fake_api(monkeypatch, {})
    ollama = RecordingProvider()
    with pytest.raises(LLMUnavailable) as e:
        await online(pool_for(tempfile.mkdtemp()), ollama=ollama).chat_text("s", "u")
    assert e.value.code == "grok_not_configured" and ollama.seen == []


async def test_the_second_provider_gets_the_same_redacted_prompt(monkeypatch):
    sent = fake_api(monkeypatch, {"groq.com": limit("Too many requests"), "mistral.ai": (200, OK)})
    await online(pool_for(tempfile.mkdtemp(), groq_api_key="gk", mistral_api_key="mk")).chat_text(
        "sys", "Priya Sharma\nmail priya@x.com\nPriya built Kafka services.")
    body = json.dumps(sent[1][1]["json"])
    assert "priya@x.com" not in body and "Priya" not in body and "Kafka" in body


async def test_a_service_with_no_credits_is_skipped_not_reported_as_a_bad_key(monkeypatch):
    fake_api(monkeypatch, {"x.ai": (403, {"code": "permission-denied", "error": "Your team doesn't have any credits or licenses yet."}), "groq.com": (200, OK)})
    pool = pool_for(tempfile.mkdtemp(), order="xai,groq", xai_api_key="xk", groq_api_key="gk")
    assert await online(pool).chat_json("s", "u", SCHEMA) == {"summary": "ok"}
    assert any(k.startswith("Grok") for k in pool.until)
