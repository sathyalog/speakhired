import io
from functools import lru_cache

from ..config import get_settings
from .language import decide_audio_language
from .vocab import whisper_prompt

IT_PROMPT = ("Um, so, I worked with Kubernetes, Kafka, PostgreSQL, REST APIs, CI/CD pipelines, Docker, "
             "microservices, Spring Boot, React, AWS, and SQL. Uh, yeah.")


class VoiceNotInstalled(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _model():
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise VoiceNotInstalled("Install voice extras: uv sync --extra voice") from e
    return WhisperModel(get_settings().whisper_model, compute_type="int8")


def _run(audio: bytes, language: str | None, terms: list[str] | None = None):
    prompt, hot = whisper_prompt(terms or [])
    segments, info = _model().transcribe(
        io.BytesIO(audio), language=language, beam_size=5, word_timestamps=True,
        condition_on_previous_text=False, initial_prompt=prompt, hotwords=hot or None, vad_filter=True)
    words, parts = [], []
    for seg in segments:
        parts.append(seg.text)
        for w in seg.words or []:
            words.append({"word": w.word.strip(), "start": w.start, "end": w.end, "prob": w.probability})
    return {"text": " ".join(p.strip() for p in parts).strip(), "duration": info.duration, "words": words}, info


def transcribe(audio: bytes, terms: list[str] | None = None) -> dict:
    """Auto-detects the spoken language so non-English speech can be flagged instead of being forced into English."""
    result, info = _run(audio, None, terms)
    probs = dict(getattr(info, "all_language_probs", None) or [(info.language, info.language_probability)])
    decision = decide_audio_language(probs)
    if decision["ambiguous"]:  # probably accented English that Whisper mislabelled: decode again as English
        result, _ = _run(audio, "en", terms)
        decision = {"code": "en", "prob": probs.get("en", 0.0), "non_english": False, "ambiguous": False}
    result["language"] = {"code": decision["code"], "prob": round(decision["prob"], 3), "non_english": decision["non_english"]}
    return result
