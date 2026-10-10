import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "qwen3:4b"))
    ollama_keep_alive: str = field(default_factory=lambda: _env("OLLAMA_KEEP_ALIVE", "30m"))
    ollama_max_tokens: int = field(default_factory=lambda: int(_env("OLLAMA_MAX_TOKENS", "1000")))
    lev_mode: str = field(default_factory=lambda: _env("LEV_MODE", "off"))
    lev_checkpoint: str = field(default_factory=lambda: _env("LEV_CHECKPOINT", "interfaze-ai/lev"))
    lev_cache_dir: str = field(default_factory=lambda: _env("LEV_CACHE_DIR", ""))
    lev_local_force: bool = field(default_factory=lambda: _env("LEV_LOCAL_FORCE", "false").lower() == "true")
    lev_url: str = field(default_factory=lambda: _env("LEV_URL", "http://localhost:8000"))
    modal_key: str = field(default_factory=lambda: _env("MODAL_KEY", ""))
    modal_secret: str = field(default_factory=lambda: _env("MODAL_SECRET", ""))
    lev_allow_remote: bool = field(default_factory=lambda: _env("LEV_ALLOW_REMOTE", "false").lower() == "true")
    external_api_base: str = field(default_factory=lambda: _env("EXTERNAL_API_BASE", "https://api.x.ai/v1"))
    external_api_key: str = field(default_factory=lambda: _env("EXTERNAL_API_KEY", "") or _env("GROK_API_KEY", "") or _env("XAI_API_KEY", ""))
    external_model: str = field(default_factory=lambda: _env("EXTERNAL_MODEL", "grok-4.7"))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "small"))
    default_voice: str = field(default_factory=lambda: _env("DEFAULT_VOICE", "bm_george"))
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")))


def get_settings() -> Settings:
    return Settings()
