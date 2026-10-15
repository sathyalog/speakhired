import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient  # noqa: E402

from speakhired import main  # noqa: E402


class FakeLLM:
    async def chat_json(self, system, user, schema, temperature=0.2):
        props = schema.get("properties", {})
        if "company" in props:
            return {"company": "Acme", "role": "Backend Engineer", "seniority": "mid", "tech_stack": ["Kafka", "Python"], "responsibilities": ["build APIs"]}
        if "skills" in props:
            return {"skills": ["Python", "Kafka"], "projects": ["Order service"], "claims": ["used Kafka for 2 years"]}
        if "questions" in props:
            return {"questions": [{"text": "What is a Kafka consumer group?", "topic": "Kafka", "kind": "technical", "key_points": ["parallelism", "offsets"]}] * 4}
        if "scores" in props:
            return {"scores": {k: 4 for k in ["relevance", "correctness", "depth", "structure", "specificity"]},
                    "evidence": {"relevance": "consumer group"}, "covered_points": ["offsets"], "missed_points": ["parallelism"],
                    "answered": True, "next_action": "next_question"}
        if "swaps" in props or "corrections" in props:
            return {"corrections": [], "swaps": [], "missing_outline": ["parallelism"], "vocabulary_tips": [], "spoken_summary": "Good start.",
                    "impressive": {"answer_first": "A consumer group shares partitions.", "example": "e", "trade_off": "t", "close": "c"}}
        return {"key_points": ["a", "b"]}

    async def chat_text(self, system, user, temperature=0.6):
        return "Strong basics. Practise explaining trade-offs."


def test_full_round_flow():
    main.llm = FakeLLM()
    c = TestClient(main.app)
    r = c.post("/api/sessions", data={"round_no": "1", "jd_text": "We need a backend engineer with Kafka and Python."},
               files={"resume": ("cv.txt", b"Priya. Python and Kafka developer.", "text/plain")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job"]["company"] == "Acme" and body["total"] == 5 + 4
    sid = body["id"]
    done = False
    n = 0
    while not done:
        a = c.post(f"/api/sessions/{sid}/answer", json={"transcript": "A consumer group shares partitions um.", "duration": 5})
        assert a.status_code == 200, a.text
        done = a.json()["done"]
        n += 1
    assert n == body["total"]
    assert c.post(f"/api/sessions/{sid}/answer", json={"transcript": "x"}).status_code == 409
    rep = c.get(f"/api/sessions/{sid}/report").json()
    assert rep["averages"]["depth"] == 4.0 and len(rep["results"]) == n


def test_requires_jd_and_valid_round():
    c = TestClient(main.app)
    files = {"resume": ("cv.txt", b"x", "text/plain")}
    assert c.post("/api/sessions", data={"round_no": "9", "jd_text": "x"}, files=files).status_code == 400
    assert c.post("/api/sessions", data={"round_no": "1"}, files=files).status_code == 400


def test_jd_url_blocks_private_hosts():
    c = TestClient(main.app)
    r = c.post("/api/sessions", data={"round_no": "1", "jd_url": "http://127.0.0.1:8000/x"}, files={"resume": ("cv.txt", b"x", "text/plain")})
    assert r.status_code == 400


def test_interview_pattern_is_optional_and_reported():
    main.llm = FakeLLM()
    c = TestClient(main.app)
    files = {"resume": ("cv.txt", b"Priya. Python and Kafka developer.", "text/plain")}
    with_pattern = c.post("/api/sessions", data={"round_no": "2", "jd_text": "Backend engineer, Kafka and Python.",
                                                  "interview_pattern": "Two rounds: a Python coding test, then a system design."}, files=files)
    assert with_pattern.status_code == 200 and with_pattern.json()["pattern_used"] is True
    without = c.post("/api/sessions", data={"round_no": "2", "jd_text": "Backend engineer, Kafka and Python."}, files=files)
    assert without.status_code == 200 and without.json()["pattern_used"] is False
