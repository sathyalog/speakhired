import io
import re
from functools import lru_cache

from .stt import VoiceNotInstalled

# Kokoro British English voices (lang_code 'b'). Confirm IDs against the installed Kokoro version.
VOICES = [
    {"id": "bf_emma", "name": "Emma", "gender": "female", "persona": "Friendly HR recruiter", "round": 1},
    {"id": "bm_george", "name": "George", "gender": "male", "persona": "Engineering manager", "round": 2},
    {"id": "bf_isabella", "name": "Isabella", "gender": "female", "persona": "Hiring manager", "round": 3},
    {"id": "bm_lewis", "name": "Lewis", "gender": "male", "persona": "Principal engineer", "round": 4},
]
VOICE_IDS = {v["id"] for v in VOICES}


@lru_cache(maxsize=1)
def _pipeline():
    try:
        from kokoro import KPipeline
    except ImportError as e:
        raise VoiceNotInstalled("Install voice extras: uv sync --extra voice") from e
    return KPipeline(lang_code="b")


SAMPLE_RATE = 24000
DEFAULT_SPEED = 0.95      # a touch slower than Kokoro's default is clearer for listening practice
PAUSE_SECONDS = 0.3       # between sentences


def synthesize(text: str, voice: str, speed: float = DEFAULT_SPEED) -> bytes:
    import numpy as np
    import soundfile as sf
    from .vocab import prepare_speech
    if voice not in VOICE_IDS:
        raise ValueError("unknown voice")
    spoken = prepare_speech(text[:1500])
    sentences = [x for x in re.split(r"(?<=[.!?;:])\s+", spoken) if x.strip()] or [spoken]
    silence = np.zeros(int(SAMPLE_RATE * PAUSE_SECONDS), dtype="float32")
    chunks = []
    for sentence in sentences:
        for _, _, audio in _pipeline()(sentence, voice=voice, speed=max(0.7, min(1.3, speed))):
            chunks.append(np.asarray(audio, dtype="float32"))
        chunks.append(silence)
    buf = io.BytesIO()
    sf.write(buf, np.concatenate(chunks), SAMPLE_RATE, format="WAV")
    return buf.getvalue()
