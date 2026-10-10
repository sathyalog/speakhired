"""LEV (System One) client: calibrated yes/no, choice and score decisions in one forward pass.

LEV is a classifier, not a generator. Modes:
  local - loaded inside this app (needs the `lev` package and about 16 GB of memory); nothing leaves the computer
  http  - a `lev serve` server: on this computer, on your network, or your own Modal app
  off   - not used; the AI model scores answers itself
"""
import asyncio
import ipaddress
import threading
from urllib.parse import urlparse

import httpx

from ..config import Settings, get_settings
from ..sysinfo import ram_gb

LOCAL_MIN_RAM_GB = 12   # LEV is about 8 GB on its own; below this the computer would grind to a halt


class LevUnavailable(Exception):
    pass


def _is_loopback(host: str) -> bool:
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_private_host(host: str) -> bool:
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local") or host.endswith(".ts.net"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


def validate_lev_url(url: str, allow_remote: bool) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise LevUnavailable("invalid LEV_URL")
    if _is_private_host(u.hostname):
        return
    if not (allow_remote and u.scheme == "https"):
        raise LevUnavailable("remote LEV hosts need LEV_ALLOW_REMOTE=true and https (answers would leave this network)")


class LevClient:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()
        self._engine = None
        self._load_error = ""
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.s.lev_mode in ("http", "local")

    @property
    def in_process(self) -> bool:
        return self.s.lev_mode == "local"

    @property
    def is_remote(self) -> bool:
        """True when LEV runs outside this machine/LAN (e.g. a Modal deployment)."""
        if self.in_process:
            return False
        host = urlparse(self.s.lev_url).hostname or ""
        return not _is_private_host(host)

    # ----- in-process engine -----
    def _load_engine(self):
        """Blocking: loads the model once. Safe to call from several threads."""
        with self._lock:
            if self._engine is not None:
                return self._engine
            ram = ram_gb()
            if ram and ram < LOCAL_MIN_RAM_GB and not self.s.lev_local_force:
                self._load_error = (f"LEV inside the app needs about 16 GB of memory and this computer has {ram:.0f} GB, so it was not loaded "
                                    "(it would make the computer crawl). Run LEV on another computer with LEV_MODE=http, or set LEV_MODE=off. "
                                    "To try anyway, set LEV_LOCAL_FORCE=true.")
                raise LevUnavailable(self._load_error)
            try:
                import lev  # type: ignore
            except ImportError as e:
                self._load_error = "LEV is not installed. Run: uv sync --extra lev (it needs Python 3.12 or newer and downloads about 8 GB the first time)."
                raise LevUnavailable(self._load_error) from e
            try:
                self._engine = lev.load(self.s.lev_checkpoint, cache_dir=self.s.lev_cache_dir or None)
            except Exception as e:  # noqa: BLE001 - download, memory or format problems
                self._load_error = f"LEV could not be loaded: {type(e).__name__}: {str(e)[:200]}"
                raise LevUnavailable(self._load_error) from e
            self._load_error = ""
            return self._engine

    def try_preload(self) -> None:
        """Called in the background at start-up so the first answer is not kept waiting for the model to load."""
        try:
            self._load_engine()
        except LevUnavailable:
            pass   # the reason is kept for the health check and shown when LEV is first needed

    async def _decide_local(self, state: str, questions: dict) -> dict:
        engine = await asyncio.to_thread(self._load_engine)
        try:
            response = await asyncio.to_thread(engine.system_one, state, questions)
        except (ValueError, TypeError, RuntimeError) as e:
            raise LevUnavailable(f"LEV rejected the request: {e}") from e
        return response.model_dump()["answers"]

    @property
    def location(self) -> str:
        """Where LEV runs, for telling the user honestly where their text goes: off, this_computer, network or internet."""
        if not self.enabled:
            return "off"
        if self.in_process:
            return "this_computer"
        host = urlparse(self.s.lev_url).hostname or ""
        return "this_computer" if _is_loopback(host) else "network" if _is_private_host(host) else "internet"

    def _headers(self) -> dict:
        h = {"Authorization": "Bearer local"}
        # Modal proxy-auth tokens (https://modal.com/docs/guide/webhook-proxy-auth)
        if self.s.modal_key and self.s.modal_secret:
            h["Modal-Key"] = self.s.modal_key
            h["Modal-Secret"] = self.s.modal_secret
        return h

    async def decide(self, state: str, questions: dict) -> dict:
        """Returns {name: answer}. `state` must already be redacted by the caller."""
        if not self.enabled:
            raise LevUnavailable("LEV is off")
        if self.in_process:
            return await self._decide_local(state, questions)
        validate_lev_url(self.s.lev_url, self.s.lev_allow_remote)
        try:
            # Remote serverless hosts can cold-start for a while, so allow a long first call.
            async with httpx.AsyncClient(timeout=180 if self.is_remote else 30) as client:
                r = await client.post(
                    f"{self.s.lev_url}/v1/systemone",
                    headers=self._headers(),
                    json={"state": state, "questions": questions},
                )
            if r.status_code == 529:
                raise LevUnavailable("LEV model still loading")
            r.raise_for_status()
            return r.json()["answers"]
        except httpx.HTTPError as e:
            raise LevUnavailable(str(e)) from e

    async def health(self) -> dict:
        if not self.enabled:
            return {"mode": self.s.lev_mode, "ok": False}
        if self.in_process:
            loaded = self._engine is not None
            return {"mode": "local", "ok": loaded, "remote": False, "status": "ok" if loaded else ("not loaded" if self._load_error else "loading"),
                    **({"error": self._load_error} if self._load_error else {}), "ram_gb": round(ram_gb())}
        try:
            async with httpx.AsyncClient(timeout=60 if self.is_remote else 3) as client:
                r = await client.get(f"{self.s.lev_url}/health", headers=self._headers())
            body = r.json() if r.status_code == 200 else {}
            return {"mode": self.s.lev_mode, "ok": r.status_code == 200, "remote": self.is_remote, **body}
        except Exception as e:  # noqa: BLE001
            return {"mode": self.s.lev_mode, "ok": False, "error": str(e)}
