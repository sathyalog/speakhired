"""Language-model providers and the router that picks one.

Offline mode: Ollama on this computer. Online mode: Grok (any OpenAI-compatible endpoint) with your own key.
Every prompt goes through the same privacy step first: personal details become tokens like [NAME_1] and are
put back into the answer afterwards, so no provider ever sees them.
"""
import contextvars
import copy
import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Protocol

import httpx

from .config import Settings, get_settings
from .privacy import Redactor


class LLMUnavailable(Exception):
    """A model could not be used. `code` lets the UI explain why (for example grok_not_configured).
    `daily` is set when a usage limit is a per-day quota, so the provider stays paused until the next UTC midnight."""

    def __init__(self, code: str, message: str, daily: bool = False):
        super().__init__(message)
        self.code, self.message, self.daily = code, message, daily


# Errors raised while serving one request, so the API can tell the browser to show a notice even when a feature
# carried on with a fallback (for example the rules-only resume score).
llm_errors: contextvars.ContextVar[list[tuple[str, str]] | None] = contextvars.ContextVar("llm_errors", default=None)

# Notices that an answer came from a different online provider after the first one ran out of its limit.
llm_switches: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("llm_switches", default=None)


def record_error(code: str, message: str) -> None:
    bucket = llm_errors.get()
    if bucket is not None and (code, message) not in bucket:
        bucket.append((code, message))


def record_switch(message: str) -> None:
    bucket = llm_switches.get()
    if bucket is not None and message not in bucket:
        bucket.append(message)


# Usage-limit errors move the request to the next provider. Other failures (bad key, unknown model) do not, because
# another provider will not fix them and the user should see the real problem.
SWITCH_CODES = {"grok_rate"}


class LLM(Protocol):
    async def chat_json(self, system: str, user: str, schema: dict[str, Any], temperature: float = 0.2) -> dict: ...
    async def chat_text(self, system: str, user: str, temperature: float = 0.6) -> str: ...


class OllamaLLM:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()

    async def _chat(self, payload: dict) -> str:
        # Speed on small computers: thinking models (Qwen3) otherwise write about two thirds of their output as hidden reasoning,
        # the model stays loaded between requests, and a runaway answer is cut off.
        payload = {**payload, "think": False, "keep_alive": self.s.ollama_keep_alive}
        payload["options"] = {**payload.get("options", {}), "num_predict": self.s.ollama_max_tokens}
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                r = await client.post(f"{self.s.ollama_url}/api/chat", json=payload)
                if r.status_code == 400 and "think" in r.text.lower():      # a model that does not know the option
                    payload.pop("think")
                    r = await client.post(f"{self.s.ollama_url}/api/chat", json=payload)
                r.raise_for_status()
                return r.json()["message"]["content"]
        except httpx.ConnectError as e:
            raise LLMUnavailable("ollama_unavailable", "Ollama is not running. Start it, or switch to Online mode.") from e
        except httpx.HTTPError as e:
            raise LLMUnavailable("ollama_error", f"Ollama could not answer: {type(e).__name__}") from e

    def _messages(self, system: str, user: str) -> list[dict]:
        # "/no_think" turns off Qwen3 reasoning traces for fast, clean output.
        return [{"role": "system", "content": system}, {"role": "user", "content": user + "\n/no_think"}]

    async def chat_json(self, system: str, user: str, schema: dict[str, Any], temperature: float = 0.2) -> dict:
        content = await self._chat({
            "model": self.s.ollama_model, "stream": False, "format": schema,
            "messages": self._messages(system, user), "options": {"temperature": temperature},
        })
        return json.loads(content)

    async def chat_text(self, system: str, user: str, temperature: float = 0.6) -> str:
        content = await self._chat({
            "model": self.s.ollama_model, "stream": False,
            "messages": self._messages(system, user), "options": {"temperature": temperature},
        })
        return content.strip()

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{self.s.ollama_url}/api/tags")
                names = [m["name"] for m in r.json().get("models", [])]
            return {"ok": True, "model_ready": any(n.startswith(self.s.ollama_model.split(":")[0]) for n in names), "models": names}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}


def strictify(schema: dict) -> dict:
    """Strict structured output (Groq, OpenAI, xAI) wants every object closed and every field listed as required."""
    def walk(node):
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        node = {k: walk(v) if k in ("items", "anyOf", "oneOf", "allOf", "properties", "$defs") else v for k, v in node.items()}
        if node.get("type") == "object" or "properties" in node:
            props = {k: walk(v) for k, v in node.get("properties", {}).items()}
            node["properties"], node["required"], node["additionalProperties"] = props, list(props), False
        return node
    return walk(copy.deepcopy(schema))


class GrokLLM:
    """The online provider: xAI Grok or Groq (or any OpenAI-compatible service), with your own key from .env."""

    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()

    @property
    def configured(self) -> bool:
        return bool(self.s.external_api_key)

    def status(self) -> list[dict]:
        return [{"provider": self.provider, "model": self.s.external_model, "configured": self.configured, "paused_until": None}]

    @property
    def provider(self) -> str:
        base = self.s.external_api_base.lower()
        names = {"x.ai": "Grok", "groq.com": "Groq", "mistral.ai": "Mistral", "googleapis.com": "Google AI Studio"}
        return next((label for host, label in names.items() if host in base), urlparse(base).hostname or "AI service")

    def _check_key_matches_service(self) -> None:
        key, base = self.s.external_api_key, self.s.external_api_base.lower()
        if key.startswith("gsk_") and "groq.com" not in base:
            raise LLMUnavailable("grok_wrong_service", "Your key starts with gsk_, which is a Groq key. Put it on the GROQ_API_KEY line in your .env file.")
        if key.startswith("xai-") and "x.ai" not in base:
            raise LLMUnavailable("grok_wrong_service", "Your key starts with xai-, which is an xAI Grok key. Put it on the XAI_API_KEY line in your .env file.")

    async def _post(self, body: dict) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                return await client.post(f"{self.s.external_api_base}/chat/completions", json={"model": self.s.external_model, **body},
                                         headers={"Authorization": f"Bearer {self.s.external_api_key}"})
        except httpx.HTTPError as e:
            raise LLMUnavailable("grok_unreachable", f"Couldn't reach {self.provider}. Check your internet connection, or switch to Offline mode.") from e

    @staticmethod
    def _detail(r: httpx.Response) -> str:
        try:
            err = r.json().get("error")
            return (err.get("message") if isinstance(err, dict) else str(err))[:160]
        except Exception:  # noqa: BLE001
            return r.text[:160]

    def _fail(self, r: httpx.Response) -> LLMUnavailable:
        who, detail, low = self.provider, self._detail(r), self._detail(r).lower()
        # A 403 can mean "monthly quota used up" as well as "bad key", so the wording decides which one it is.
        # "no credits" is a 403 too: that service cannot answer until it is topped up, so the app moves on.
        if r.status_code in (402, 429) or (r.status_code == 403 and any(w in low for w in ("quota", "limit", "exceed", "credit"))):
            daily = any(w in low for w in ("per day", "daily", "day", "quota", "month", "credit"))
            return LLMUnavailable("grok_rate", f"{who} says you've hit a usage limit.", daily=daily)
        if r.status_code in (401, 403) or (r.status_code == 400 and "api key" in low):
            return LLMUnavailable("grok_auth", f"{who} did not accept the key. Check its key in your .env file.")
        if r.status_code in (400, 404) and "model" in low:
            return LLMUnavailable("grok_model", f"{who} does not know the model '{self.s.external_model}'. Check its model name in your .env file. ({detail})")
        return LLMUnavailable("grok_error", f"{who} returned an error ({r.status_code}): {detail}")

    async def _chat(self, body: dict) -> str:
        if not self.configured:
            raise LLMUnavailable("grok_not_configured", f"{self.provider} key is not configured. Add EXTERNAL_API_KEY to your .env file, or switch to Offline mode.")
        self._check_key_matches_service()
        r = await self._post(body)
        if r.status_code >= 400:
            raise self._fail(r)
        return r.json()["choices"][0]["message"]["content"]

    async def chat_json(self, system: str, user: str, schema: dict[str, Any], temperature: float = 0.2) -> dict:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if not self.configured:
            raise LLMUnavailable("grok_not_configured", f"{self.provider} key is not configured. Add EXTERNAL_API_KEY to your .env file, or switch to Offline mode.")
        self._check_key_matches_service()
        closed = strictify(schema)
        last = None
        # Strict schema first; services differ in what they accept, so step down rather than fail.
        for fmt in ({"type": "json_schema", "json_schema": {"name": "result", "schema": closed, "strict": True}},
                    {"type": "json_schema", "json_schema": {"name": "result", "schema": closed, "strict": False}},
                    {"type": "json_object"}):
            m = msgs if fmt["type"] != "json_object" else [{"role": "system", "content": system + "\nReply with one JSON object matching this JSON Schema:\n" + json.dumps(closed)}, msgs[1]]
            r = await self._post({"messages": m, "temperature": temperature, "response_format": fmt})
            if r.status_code < 400:
                try:
                    return json.loads(r.json()["choices"][0]["message"]["content"])
                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    last = LLMUnavailable("grok_error", f"{self.provider} sent an answer in an unexpected format. Try again.")
                    continue
            err = self._fail(r)
            if err.code != "grok_error":
                raise err  # key, rate limit and model problems will not be fixed by another format
            last = err
        raise last or LLMUnavailable("grok_error", f"{self.provider} did not return a usable answer.")

    async def chat_text(self, system: str, user: str, temperature: float = 0.6) -> str:
        return (await self._chat({"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": temperature})).strip()


class ModeStore:
    """Remembers whether the app is in offline or online mode, across restarts."""

    MODES = ("offline", "online")

    def __init__(self, path: Path | None = None, default: str = "offline"):
        self.path = path or Path(get_settings().data_dir) / "mode.json"
        self.mode = default
        try:
            saved = json.loads(self.path.read_text()).get("mode")
            if saved in self.MODES:
                self.mode = saved
        except (OSError, ValueError):
            pass

    def set(self, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError("mode must be 'offline' or 'online'")
        self.mode = mode
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"mode": mode}))
        except OSError:
            pass


def build_online_providers(s: Settings) -> list[GrokLLM]:
    """One client per online provider that has a key, in LLM_PROVIDER_ORDER. Each is a copy of the settings with
    that provider's address, key and model, so the request code stays the same for all of them."""
    slots = {
        "groq": (s.groq_api_key, "https://api.groq.com/openai/v1", s.groq_model),
        "mistral": (s.mistral_api_key, "https://api.mistral.ai/v1", s.mistral_model),
        "gemini": (s.gemini_api_key, "https://generativelanguage.googleapis.com/v1beta/openai", s.gemini_model),
        "xai": (s.xai_api_key, "https://api.x.ai/v1", s.xai_model),
        "custom": (s.external_api_key, s.external_api_base, s.external_model),
    }
    order = [name.strip().lower() for name in s.llm_provider_order.split(",") if name.strip()]
    order += [name for name in slots if name not in order]
    providers, seen_keys = [], set()
    for name in order:
        key, base, model = slots.get(name, ("", "", ""))
        if not key or key in seen_keys:  # the same key listed twice (for example in EXTERNAL_API_KEY too) is used once
            continue
        seen_keys.add(key)
        providers.append(GrokLLM(replace(s, external_api_key=key, external_api_base=base, external_model=model)))
    return providers


class CooldownStore:
    """Which providers have run out of their limit, and until when. Kept on disk so a restart does not retry them."""

    def __init__(self, path: Path | None = None):
        self.path = path or Path(get_settings().data_dir) / "llm_cooldown.json"

    def load(self) -> dict[str, float]:
        try:
            return {k: float(v) for k, v in json.loads(self.path.read_text()).items()}
        except (OSError, ValueError, AttributeError):
            return {}

    def save(self, until: dict[str, float]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(until))
        except OSError:
            pass


def _next_utc_midnight(now: float) -> float:
    day = datetime.fromtimestamp(now, tz=timezone.utc).date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()


class ProviderPool:
    """Tries the online providers in order. When one reaches its usage limit it is paused and the same request goes
    to the next one, so the interview carries on. The prompt is already redacted before it gets here, so every
    provider sees the same protected text."""

    def __init__(self, providers: list[GrokLLM], store: CooldownStore | None = None, clock=time.time):
        # With no key set at all, keep one client so the user still gets the clear "key is not configured" message.
        self.providers = providers or [GrokLLM()]
        self.store, self.clock = store, clock  # store=None keeps pauses in memory only
        self.until = store.load() if store else {}

    def _key(self, p: GrokLLM) -> str:
        return f"{p.provider}|{p.s.external_api_base}|{p.s.external_model}"

    def _cooling(self, p: GrokLLM) -> bool:
        return self.until.get(self._key(p), 0) > self.clock()

    @property
    def configured(self) -> bool:
        return any(p.configured for p in self.providers)

    def active(self) -> GrokLLM:
        """The provider that will answer next: the first one with a key that is not paused."""
        return next((p for p in self.providers if p.configured and not self._cooling(p)), self.providers[0])

    @property
    def provider(self) -> str:
        return self.active().provider

    @property
    def s(self) -> Settings:
        return self.active().s

    def status(self) -> list[dict]:
        return [{"provider": p.provider, "model": p.s.external_model, "configured": p.configured,
                 "paused_until": datetime.fromtimestamp(self.until[self._key(p)], tz=timezone.utc).strftime("%H:%M UTC")
                 if self._cooling(p) else None} for p in self.providers]

    def _pause(self, p: GrokLLM, e: LLMUnavailable) -> None:
        now = self.clock()
        self.until[self._key(p)] = _next_utc_midnight(now) if e.daily else now + 60
        if self.store:
            self.store.save(self.until)

    async def run(self, call):
        """Runs `call(provider)` on the first available provider, moving on when one is at its limit."""
        first = None
        for p in self.providers:
            if not p.configured or self._cooling(p):
                continue
            try:
                result = await call(p)
            except LLMUnavailable as e:
                if e.code not in SWITCH_CODES:
                    raise
                self._pause(p, e)
                first = first or p
                continue
            if first is not None:
                record_switch(f"{first.provider} has reached its limit. Switched to {p.provider}. Please wait a few seconds.")
            return result
        if not self.configured:  # no key anywhere: let the first client raise its own "key is not configured" error
            return await call(self.providers[0])
        resets = ", ".join(f"{s['provider']} after {s['paused_until']}" for s in self.status() if s["paused_until"]) or "later"
        raise LLMUnavailable("grok_rate", f"Every online AI service has reached its usage limit. Try again {resets}, or switch to Offline mode.")


class RoutingLLM:
    """What the rest of the app talks to: picks Ollama or the online providers by mode and keeps personal details out of every prompt."""

    def __init__(self, mode: ModeStore, ollama: OllamaLLM | None = None, grok: "ProviderPool | GrokLLM | None" = None):
        self.mode, self.ollama = mode, ollama or OllamaLLM()
        self.grok = grok if isinstance(grok, ProviderPool) else ProviderPool([grok] if grok else None)

    async def chat_json(self, system: str, user: str, schema: dict[str, Any], temperature: float = 0.2) -> dict:
        red = Redactor()
        try:
            user_c = red.clean(user)  # first, so names found in the document are also hidden in the instructions
            system_c = red.clean(system)
            if self.mode.mode == "online":
                data = await self.grok.run(lambda p: p.chat_json(system_c, user_c, schema, temperature))
            else:
                data = await self.ollama.chat_json(system_c, user_c, schema, temperature)
        except LLMUnavailable as e:
            record_error(e.code, e.message)
            raise
        return red.restore_json(data)

    async def chat_text(self, system: str, user: str, temperature: float = 0.6) -> str:
        red = Redactor()
        try:
            user_c = red.clean(user)
            system_c = red.clean(system)
            if self.mode.mode == "online":
                text = await self.grok.run(lambda p: p.chat_text(system_c, user_c, temperature))
            else:
                text = await self.ollama.chat_text(system_c, user_c, temperature)
        except LLMUnavailable as e:
            record_error(e.code, e.message)
            raise
        return red.restore(text)

    async def health(self) -> dict:
        return await self.ollama.health()
