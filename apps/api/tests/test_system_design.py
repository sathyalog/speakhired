from speakhired.engines import system_design as sd
from speakhired.reasoning.lev import LevUnavailable


def shape(id_, kind="rectangle"):
    return {"id": id_, "type": kind, "isDeleted": False}


def label(id_, container, text):
    return {"id": id_, "type": "text", "containerId": container, "text": text, "isDeleted": False}


def arrow(id_, src, dst, two_way=False, start_bound=True, end_bound=True):
    return {
        "id": id_, "type": "arrow", "isDeleted": False,
        "startBinding": {"elementId": src} if start_bound else None,
        "endBinding": {"elementId": dst} if end_bound else None,
        "startArrowhead": "arrow" if two_way else None, "endArrowhead": "arrow",
    }


def sample_scene():
    return [
        shape("a"), label("ta", "a", "Load Balancer"),
        shape("b"), label("tb", "b", "API Server (stateless)"),
        shape("c"), label("tc", "c", "Postgres"),
        shape("d"),  # no label, no connections
        arrow("x", "a", "b"), label("tx", "x", "HTTP"),
        arrow("y", "b", "c", two_way=True),
        arrow("z", "b", "c", end_bound=False),  # dangling: not attached at the end
        shape("gone"),
    ]


def rubric():
    return sd.load_questions()[0]["rubric"]["components"]


def two_box_scene():
    return [shape("a"), label("ta", "a", "Load Balancer"), shape("b"), label("tb", "b", "App server"), arrow("x", "a", "b")]


def test_build_graph_reads_labels_and_bindings():
    scene = sample_scene()
    scene[-1]["isDeleted"] = True  # deleted shapes are ignored
    g = sd.build_graph(scene)
    assert [n["label"] for n in g["nodes"]] == ["Load Balancer", "API Server (stateless)", "Postgres", ""]
    assert {(e["from"], e["to"], e["label"], e["two_way"]) for e in g["edges"]} == {
        ("N1", "N2", "HTTP", False), ("N2", "N3", "", True)}
    assert g["dangling_arrows"] == 1
    assert g["unlabeled"] == ["N4"]
    assert g["isolated"] == ["N4"]


def test_evidence_needs_a_name_and_a_connection():
    g = sd.build_graph([
        shape("a"), label("ta", "a", "Postgres DB"),  # named, but not connected
        shape("b"), label("tb", "b", "Blob store"),  # "lb" inside "blob" must not match
    ])
    rows = {r["name"]: r for r in sd.component_evidence(g, rubric())}
    assert rows["Database for URL mappings"]["drawn"] and not rows["Database for URL mappings"]["candidate"]
    assert "not connected" in rows["Database for URL mappings"]["note"]
    assert not rows["Load balancer or API gateway"]["drawn"]


def test_keyword_list_box_is_not_a_candidate():
    scene = [
        shape("a"), label("ta", "a", "Redis Cache, Load Balancer, Kafka, Postgres"),
        shape("b"), label("tb", "b", "App server"),
        arrow("x", "a", "b"),
    ]
    rows = {r["name"]: r for r in sd.component_evidence(sd.build_graph(scene), rubric())}
    assert rows["Cache for hot links"]["drawn"] and not rows["Cache for hot links"]["candidate"]
    assert "several components" in rows["Cache for hot links"]["note"]


def test_empty_scene_has_no_components():
    assert not sd.has_components([])
    assert not sd.has_components([label("t", "x", "only text")])
    assert sd.has_components(sample_scene())


class FakeLEV:
    def __init__(self, yes_names=(), fail=False):
        self.enabled = True
        self.yes_names = set(yes_names)
        self.fail = fail

    async def decide(self, state, questions):
        if self.fail:
            raise LevUnavailable("model still loading")
        out = {}
        for key, q in questions.items():
            name = q["instructions"].split(": ", 1)[1].split(" (", 1)[0]
            out[key] = {"noul": 0.9 if name in self.yes_names else 0.1, "confidence": 0.8}
        return out


class FakeLLM:
    def __init__(self, review=None, judge_yes=()):
        self.review = review or {"scores": {}, "summary": "ok"}
        self.judge_yes = set(judge_yes)
        self.calls = []

    async def chat_json(self, system, user, schema, temperature=0.2):
        self.calls.append(schema)
        if schema is sd.JUDGE_SCHEMA:
            return {"verdicts": [{"name": n, "yes": True} for n in self.judge_yes]}
        return self.review


async def test_review_with_lev_credits_only_judged_components():
    lev = FakeLEV(yes_names={"Load balancer or API gateway"})
    llm = FakeLLM(review={"scores": {"requirements": 8, "connections": 7, "correctness": 9, "tradeoffs": 6},
                          "missing_requirements": [{"requirement": "Custom alias", "why": "not drawn"}],
                          "misleading": [], "strengths": ["Clear entry point"], "summary": "Good start."})
    result = await sd.review(llm, sd.get_question("url-shortener"), two_box_scene(), lev)

    assert result["judge"] == "lev"
    assert result["checked_components"] == ["Load balancer or API gateway"]
    names = [m["name"] for m in result["missing_components"]]
    assert "Application servers" in names  # drawn and connected, but LEV said no role match
    assert "Load balancer or API gateway" not in names
    assert result["dimensions"]["components"] == 2.0  # 1 of 5 components credited
    assert llm.calls == [sd.REVIEW_SCHEMA]  # LEV judged; the LLM only wrote the review
    assert 0 <= result["score"] <= 100


async def test_review_falls_back_to_llm_judge_when_lev_is_down():
    llm = FakeLLM(judge_yes={"Application servers"})
    result = await sd.review(llm, sd.get_question("url-shortener"), two_box_scene(), FakeLEV(fail=True))

    assert result["judge"] == "llm"
    assert result["checked_components"] == ["Application servers"]
    assert sd.JUDGE_SCHEMA in llm.calls


async def test_review_without_lev_uses_llm_judge():
    llm = FakeLLM(judge_yes={"Load balancer or API gateway", "Application servers"})
    result = await sd.review(llm, sd.get_question("url-shortener"), two_box_scene(), None)
    assert result["judge"] == "llm"
    assert set(result["checked_components"]) == {"Load balancer or API gateway", "Application servers"}


async def test_no_candidates_means_no_judge_call():
    llm = FakeLLM()
    result = await sd.review(llm, sd.get_question("url-shortener"), [shape("a"), label("ta", "a", "Postgres")], FakeLEV())
    assert result["judge"] == "none" and result["checked_components"] == []
    assert llm.calls == [sd.REVIEW_SCHEMA]


def test_public_question_hides_rubric():
    q = sd.public_question(sd.load_questions()[0])
    assert "rubric" not in q and "pitfalls" not in q
    assert q["title"]


def test_tracks_and_levels_are_ordered_easy_to_hard():
    regular = sd.list_questions("regular")
    ai = sd.list_questions("ai")
    assert {q["track"] for q in regular} == {"regular"} and {q["track"] for q in ai} == {"ai"}
    for qs in (regular, ai):
        levels = [q["level"] for q in qs]
        assert levels == sorted(levels) and levels[0] == 1 and levels[-1] == 3
    assert len(sd.list_questions()) == len(regular) + len(ai)


def test_every_question_has_a_rubric_and_a_source():
    for q in sd.load_questions():
        assert q["source"] and len(q["rubric"]["components"]) >= 3, q["id"]
        assert q["scale"] and q["pitfalls"], q["id"]


def test_each_track_has_10_to_15_questions_with_unique_ids():
    for track in sd.TRACKS:
        assert 10 <= len(sd.list_questions(track)) <= 15, track
    ids = [q["id"] for q in sd.load_questions()]
    assert len(ids) == len(set(ids))


def test_endpoints_list_review_and_reject_empty(monkeypatch):
    from fastapi.testclient import TestClient
    from speakhired import main

    monkeypatch.setattr(main, "llm", FakeLLM())
    monkeypatch.setattr(main, "lev", FakeLEV())
    client = TestClient(main.app)

    questions = client.get("/api/system-design/questions").json()
    assert questions[0]["id"] == "url-shortener" and "rubric" not in questions[0]

    empty = client.post("/api/system-design/review", json={"question_id": "url-shortener", "elements": []})
    assert empty.status_code == 400

    missing = client.post("/api/system-design/review", json={"question_id": "nope", "elements": [shape("a")]})
    assert missing.status_code == 404

    ok = client.post("/api/system-design/review", json={"question_id": "url-shortener", "elements": [shape("a"), label("t", "a", "Cache")]})
    assert ok.status_code == 200 and ok.json()["graph"]["nodes"][0]["label"] == "Cache"


def test_question_endpoint_filters_by_track():
    from fastapi.testclient import TestClient
    from speakhired import main

    client = TestClient(main.app)
    ai = client.get("/api/system-design/questions", params={"track": "ai"}).json()
    assert ai and all(q["track"] == "ai" for q in ai)
    assert ai[0]["level_label"] == "Easy"
    assert client.get("/api/system-design/questions", params={"track": "nope"}).status_code == 400
