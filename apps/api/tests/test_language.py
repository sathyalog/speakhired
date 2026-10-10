import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

from fastapi.testclient import TestClient  # noqa: E402

from speakhired import main  # noqa: E402
from speakhired.agents import core  # noqa: E402
from speakhired.engines.delivery import delivery_metrics  # noqa: E402
from speakhired.engines.language import analyze_text, build_report, decide_audio_language  # noqa: E402
from speakhired.schemas import Question  # noqa: E402

ENGLISH_CORPUS = [
    "I have three years of experience building REST APIs with Spring Boot and PostgreSQL.",
    "My name is Priya and I am based in Hyderabad, working on Kafka consumers.",
    "We used Redis as a cache to reduce the main database load by about forty percent.",
    "To handle duplicate messages, I made the consumer idempotent and stored processed offsets.",
    "I led a team of four engineers and we shipped the migration to Kubernetes in two months.",
    "The bus factor on that service was one, so I documented the deployment process.",
    "Main thread blocking was the root cause, so we moved the work to a thread pool.",
    "Our CI pipeline runs unit tests, then builds a Docker image and pushes it to the registry.",
    "I prefer a monolith first, and then I split services when the team and the load grow.",
    "Tell me about yourself, why this role, and what do you know about the company?",
    "Log aggregation with Elasticsearch helped us find the slow query in minutes.",
    "I would use a hash map to get constant time lookups and keep the code simple.",
    "Basically, the trade-off is between consistency and availability under a network partition.",
    "Thank you, I am excited about the opportunity and I hope to contribute quickly.",
    "Sir, I am happy to share more details about the project architecture.",
    "I worked with Ravi Kumar from Chennai on the payment gateway integration.",
    "The deploy failed because the config key was missing, so I added a validation step.",
    "We handled the peak traffic with autoscaling and a queue in front of the workers.",
    "I am comfortable with Python, Java, SQL and a little Go for small tools.",
    "I think a to-do list app would be a good example of how I structure React state.",
]


def test_script_detection():
    words, total = analyze_text("मुझे यह काम पसंद है")
    assert total == 5 and all(w.lang == "hi" for w in words) and len(words) == 5
    assert analyze_text("నేను ఇది చేస్తాను")[0][0].lang == "te"
    assert analyze_text("நான் இதை செய்வேன்")[0][0].lang == "ta"
    assert analyze_text("ನಾನು ಇದನ್ನು ಮಾಡುತ್ತೇನೆ")[0][0].lang == "kn"


def test_romanised_words_with_english_alternatives():
    words, _ = analyze_text("Matlab I used Kafka, lekin it was slow")
    assert [w.word for w in words] == ["Matlab", "lekin"]
    assert "I mean" in words[0].english and "but" in words[1].english and {w.lang for w in words} == {"hi"}
    assert analyze_text("naaku telusu")[0][0].lang == "te"
    assert analyze_text("romba nalla irukku")[0][0].lang == "ta"


def test_no_false_positives_on_english_it_sentences():
    for sentence in ENGLISH_CORPUS:
        r = build_report(sentence)
        assert r.status == "english" and r.words == [], f"false positive: {sentence} -> {r.words}"


def test_status_levels():
    assert build_report("I used Kafka for events").status == "english"
    assert build_report("I used Kafka for events, matlab messaging").status == "mixed"
    mostly = build_report("mujhe kya karna hai matlab nahi pata")
    assert mostly.status == "non_english" and mostly.language == "hi" and mostly.language_name == "Hindi"
    assert build_report("nahi").status == "mixed"  # a single word only warns


def test_audio_language_decision():
    assert decide_audio_language({"hi": 0.93, "en": 0.04})["non_english"] is True
    accented = decide_audio_language({"hi": 0.55, "en": 0.40})  # accented English must not be blocked
    assert accented["non_english"] is False and accented["ambiguous"] is True
    assert decide_audio_language({"hi": 0.75, "en": 0.35})["non_english"] is False
    assert decide_audio_language({"en": 0.97, "hi": 0.01})["non_english"] is False
    assert build_report("I think so", {"code": "te", "prob": 0.91, "non_english": True}).language_name == "Telugu"


class SpyLLM:
    def __init__(self):
        self.users = []

    async def chat_json(self, system, user, schema, temperature=0.2):
        self.users.append(user)
        props = schema.get("properties", {})
        if "swaps" in props or ("corrections" in props and "missing_outline" in props):
            return {"corrections": [], "swaps": [{"instead_of": "matlab", "say": "I mean", "why": "English"}],
                    "impressive": {"answer_first": "a", "example": "b", "trade_off": "c", "close": "d"}, "spoken_summary": "ok"}
        if "scores" in props:
            return {"scores": {k: 3 for k in ["relevance", "correctness", "depth", "structure", "specificity"]}, "evidence": {},
                    "covered_points": [], "missed_points": [], "answered": True, "next_action": "next_question"}
        if "corrections" in props:
            return {"corrections": [], "better_version": "x", "missing_outline": [], "spoken_summary": "ok"}
        return {"key_points": ["a"], "follow_up": ""}

    async def chat_text(self, system, user, temperature=0.6):
        return "ok"


def _client_with_session(llm):
    main.llm = llm
    c = TestClient(main.app)
    r = c.post("/api/quick/sessions", json={"questions": [{"text": "What is a Kafka consumer group?"}], "voice": "bm_george"})
    return c, r.json()["id"]


def test_language_check_endpoint():
    c = TestClient(main.app)
    r = c.post("/api/language/check", json={"text": "mujhe kya karna hai matlab nahi pata"}).json()
    assert r["status"] == "non_english" and r["words"][0]["word"] == "mujhe"
    r = c.post("/api/language/check", json={"text": "I am fine", "audio_language": {"code": "hi", "prob": 0.9, "non_english": True}}).json()
    assert r["status"] == "non_english" and r["source"] == "audio"


def test_answer_blocked_when_mostly_non_english():
    c, sid = _client_with_session(SpyLLM())
    r = c.post(f"/api/sessions/{sid}/answer", json={"transcript": "mujhe kya karna hai matlab nahi pata", "duration": 5})
    assert r.status_code == 422 and "English" in r.json()["detail"] and "Hindi" in r.json()["detail"]
    r = c.post(f"/api/sessions/{sid}/answer", json={"transcript": "hello", "audio_language": {"code": "ta", "prob": 0.9, "non_english": True}})
    assert r.status_code == 422 and "Tamil" in r.json()["detail"]
    assert main.store.get(sid)["index"] == 0  # nothing was consumed


def test_mixed_answer_passes_with_flagged_words_to_coach():
    llm = SpyLLM()
    c, sid = _client_with_session(llm)
    r = c.post(f"/api/sessions/{sid}/answer", json={"transcript": "A consumer group shares partitions, matlab parallel work.", "duration": 8})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["language"]["status"] == "mixed" and body["language"]["words"][0]["word"] == "matlab"
    assert any("matlab (I mean / that is)" in u for u in llm.users)  # coach is told the English alternative
    polished = c.post(f"/api/sessions/{sid}/polish/{body['answer_index']}").json()
    assert polished["swaps"][0]["instead_of"] == "matlab"


async def test_coach_prompts_have_no_hinglish():
    q = Question(id="1", text="Q?", key_points=[])
    llm = SpyLLM()
    ev = await core.evaluate(llm, main.lev, q, "answer", delivery_metrics("x", 1))
    await core.coach(llm, q, "answer", ev, delivery_metrics("x", 1))
    assert not any("hinglish" in u.lower() for u in llm.users)
