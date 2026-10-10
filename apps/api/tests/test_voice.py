import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from speakhired import main  # noqa: E402
from speakhired.agents import core  # noqa: E402
from speakhired.engines import stt, tts  # noqa: E402
from speakhired.engines.delivery import delivery_metrics  # noqa: E402
from speakhired.schemas import Evaluation, Question  # noqa: E402

QUESTION = "When would you prefer Claude Anthropic models over ChatGPT models?"


def test_voice_reads_terms_the_way_engineers_say_them(monkeypatch):
    said = []

    def fake_pipeline():
        def run(sentence, voice, speed):
            said.append((sentence, speed))
            yield None, None, np.ones(2400, dtype="float32")
        return run
    monkeypatch.setattr(tts, "_pipeline", fake_pipeline)
    wav = tts.synthesize(QUESTION + " Think about cost, latency and safety.", "bm_george")
    assert said[0][0] == "When would you prefer Clawd Anthropic models over Chat G P T models?"
    assert len(said) == 2 and said[1][0] == "Think about cost, latency and safety." and said[0][1] == tts.DEFAULT_SPEED < 1.0
    assert wav[:4] == b"RIFF" and len(wav) > 2 * int(tts.SAMPLE_RATE * tts.PAUSE_SECONDS) * 2   # pauses between sentences are in the audio


def test_speak_endpoint_uses_the_slower_default(monkeypatch):
    seen = {}
    monkeypatch.setattr(tts, "synthesize", lambda text, voice, speed=tts.DEFAULT_SPEED: seen.update(text=text, speed=speed) or b"RIFFxxxx")
    r = TestClient(main.app).post("/api/speak", data={"text": QUESTION, "voice": "bm_george"})
    assert r.status_code == 200 and seen["speed"] == tts.DEFAULT_SPEED


def test_transcription_is_primed_and_corrected_with_the_current_question(monkeypatch):
    class Fake:
        async def chat_json(self, system, user, schema, temperature=0.2):
            props = schema.get("properties", {})
            if "key_points" in props:
                return {"key_points": ["cost", "safety"], "follow_up": ""}
            return {}
    main.llm = Fake()
    c = TestClient(main.app)
    sid = c.post("/api/quick/sessions", json={"questions": [{"text": QUESTION}], "voice": "bm_george"}).json()["id"]
    captured = {}

    def fake_transcribe(audio, terms=None):
        captured["terms"] = terms
        return {"text": "I would pick chat gpt for chatting and claud for safety", "duration": 6.0, "words": [], "language": {"code": "en", "prob": 0.99, "non_english": False}}
    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    r = c.post("/api/transcribe", files={"audio": ("a.webm", b"x", "audio/webm")}, data={"session_id": sid}).json()
    assert {"ChatGPT", "Claude", "Anthropic"} <= set(captured["terms"])          # the recogniser is told what to expect
    assert r["text"] == "I would pick ChatGPT for chatting and Claude for safety"
    assert r["heard"].startswith("I would pick chat gpt") and {"heard": "chat gpt", "fixed": "ChatGPT"} in r["corrections"]
    no_session = c.post("/api/transcribe", files={"audio": ("a.webm", b"x", "audio/webm")}).json()
    assert no_session["text"].startswith("I would pick ChatGPT")                  # general technical fixes still apply


async def test_feedback_shows_the_candidates_corrected_answer_and_a_stronger_one():
    class Coach:
        async def chat_json(self, system, user, schema, temperature=0.2):
            return {"corrections": [{"original": "I am having", "fix": "I have", "reason": "stative verb"},
                                    {"original": "chat gpt", "fix": "ChatGPT", "reason": "product name"}],
                    "swaps": [], "missing_outline": ["cost and latency", "safety and compliance"], "vocabulary_tips": [], "spoken_summary": "Good start.",
                    "impressive": {"answer_first": "I would choose Claude when safety matters.", "example": "In our bank project...", "trade_off": "It can be slower.", "close": "So I match the model to the risk."}}
    q = Question(id="1", text=QUESTION, key_points=["cost", "safety"])
    ev = Evaluation(scores={"relevance": 3}, missed_points=["cost"])
    fb = await core.quick_coach(Coach(), q, "I am having experience with chat gpt and claude.", ev, delivery_metrics("x", 1), None)
    assert fb.corrected_answer == "I have experience with ChatGPT and claude."   # only the grammar fixes, in their own words
    assert fb.missing_outline == ["cost and latency", "safety and compliance"]
    assert fb.better_version.startswith("I would choose Claude when safety matters.") and fb.impressive.example.startswith("In our bank")
