"""Language-model providers and the router that picks one.

Offline mode: Ollama on this computer. Online mode: Grok (any OpenAI-compatible endpoint) with your own key.
Every prompt goes through the same privacy step first: personal details become tokens like [NAME_1] and are
put back into the answer afterwards, so no provider ever sees them.
"""
import contextvars
import copy
import json
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Protocol

import httpx

from .config import Settings, get_settings
from .privacy import Redactor


class LLMUnavailable(Exception):
    """A model could not be used. `code` lets the UI explain why (for example grok_not_configured)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# Errors raised while serving one request, so the API can tell the browser to show a notice even when a feature
# carried on with a fallback (for example the rules-only resume score).
llm_errors: contextvars.ContextVar[list[tuple[str, str]] | None] = contextvars.ContextVar("llm_errors", default=None)


def record_error(code: str, message: str) -> None:
    bucket = llm_errors.get()
    if bucket is not None and (code, message) not in bucket:
        bucket.append((code, message))


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

    @property
    def provider(self) -> str:
        base = self.s.external_api_base.lower()
        return "Grok" if "x.ai" in base else "Groq" if "groq.com" in base else (urlparse(base).hostname or "AI service")

    def _check_key_matches_service(self) -> None:
        key, base = self.s.external_api_key, self.s.external_api_base.lower()
        if key.startswith("gsk_") and "groq.com" not in base:
            raise LLMUnavailable("grok_wrong_service", "Your key starts with gsk_, which is a Groq key. Set EXTERNAL_API_BASE=https://api.groq.com/openai/v1 and EXTERNAL_MODEL=openai/gpt-oss-120b in your .env file.")
        if key.startswith("xai-") and "x.ai" not in base:
            raise LLMUnavailable("grok_wrong_service", "Your key starts with xai-, which is an xAI Grok key. Set EXTERNAL_API_BASE=https://api.x.ai/v1 and EXTERNAL_MODEL=grok-4.7 in your .env file.")

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
        who, detail = self.provider, self._detail(r)
        if r.status_code in (401, 403) or (r.status_code == 400 and "api key" in detail.lower()):
            return LLMUnavailable("grok_auth", f"{who} did not accept the key. Check EXTERNAL_API_KEY and EXTERNAL_API_BASE in your .env file.")
        if r.status_code == 429:
            return LLMUnavailable("grok_rate", f"{who} says you've hit a usage limit. Try again shortly, or switch to Offline mode.")
        if r.status_code in (400, 404) and "model" in detail.lower():
            return LLMUnavailable("grok_model", f"{who} does not know the model '{self.s.external_model}'. Set EXTERNAL_MODEL in your .env file. ({detail})")
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


class RoutingLLM:
    """What the rest of the app talks to: picks Ollama or Grok by mode and keeps personal details out of every prompt."""

    def __init__(self, mode: ModeStore, ollama: OllamaLLM | None = None, grok: GrokLLM | None = None):
        self.mode, self.ollama, self.grok = mode, ollama or OllamaLLM(), grok or GrokLLM()

    def _provider(self):
        return self.grok if self.mode.mode == "online" else self.ollama

    async def chat_json(self, system: str, user: str, schema: dict[str, Any], temperature: float = 0.2) -> dict:
        red = Redactor()
        try:
            user_c = red.clean(user)  # first, so names found in the document are also hidden in the instructions
            data = await self._provider().chat_json(red.clean(system), user_c, schema, temperature)
        except LLMUnavailable as e:
            record_error(e.code, e.message)
            raise
        return red.restore_json(data)

    async def chat_text(self, system: str, user: str, temperature: float = 0.6) -> str:
        red = Redactor()
        try:
            user_c = red.clean(user)
            text = await self._provider().chat_text(red.clean(system), user_c, temperature)
        except LLMUnavailable as e:
            record_error(e.code, e.message)
            raise
        return red.restore(text)

    async def health(self) -> dict:
        return await self.ollama.health()
