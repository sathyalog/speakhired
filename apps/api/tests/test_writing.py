import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

from fastapi.testclient import TestClient  # noqa: E402

from speakhired import main  # noqa: E402
from speakhired.agents import writing  # noqa: E402

DRAFT = ("Dear Hiring Manager,\n\nI am writing this email to you in order to express my interest in the position of Backend Engineer that "
         "was advertised on your website.\n\nIn my current role I have worked on many different things including APIs and databases.\n\n"
         "Thanks and regards,\nPriya")


class Fake:
    def __init__(self):
        self.users = []

    async def chat_json(self, system, user, schema, temperature=0.2):
        self.users.append(user)
        return {"issues": [
            {"original": "in order to express", "replacement": "to express", "category": "concise", "message": "Shorter"},
            {"original": "worked on many different things", "replacement": "built APIs and databases", "category": "clarity", "message": "Be specific"},
            {"original": "words that are not in the draft", "replacement": "x", "category": "clarity", "message": "n/a"},
            {"original": "in order to", "replacement": "to", "category": "concise", "message": "overlaps the first issue"},
            {"original": "Priya", "replacement": "Priya", "category": "tone", "message": "no change"},
        ]}

    async def chat_text(self, system, user, temperature=0.6):
        return "Rewritten draft."


def test_chunks_cover_text_without_gaps_or_overlap():
    text = ("Paragraph one sentence. " * 30 + "\n\n") * 6
    spans = writing.chunks_of(text)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:])) and all(e - s <= writing.CHUNK + 5 for s, e in spans)


async def test_issues_are_located_validated_and_deduplicated():
    r = await writing.improve(Fake(), DRAFT, "recruiter_email", "professional")
    assert [i.original for i in r.issues] == ["in order to express", "worked on many different things"]
    for i in r.issues:
        assert DRAFT[i.start:i.end] == i.original
    assert r.rewrite is None and r.truncated is False


async def test_long_text_is_truncated_and_chunked():
    llm = Fake()
    r = await writing.improve(llm, ("This is a fairly ordinary sentence about my work. " * 200), "general", "concise", rewrite=True)
    assert r.truncated is True and len(llm.users) >= 5 and r.rewrite == "Rewritten draft."
    assert all(len(u) <= writing.CHUNK + 5 for u in llm.users)


def test_endpoint():
    main.llm = Fake()
    c = TestClient(main.app)
    assert c.post("/api/write/improve", json={"text": "   "}).status_code == 400
    r = c.post("/api/write/improve", json={"text": DRAFT, "kind": "cover_letter", "tone": "confident"})
    assert r.status_code == 200 and len(r.json()["issues"]) == 2
