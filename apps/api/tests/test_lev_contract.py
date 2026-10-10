"""LEV rejects requests that do not match its schema (HTTP 422), so these tests mirror its rules from lev/types.py:
  noul   - criteria optional, a dict with only "true"/"false" keys
  choice - criteria a dict of at least 2 options
  score  - criteria an ORDERED LIST of 2 to 10 level descriptions; the answer `score` is the expected level index (0 .. n-1)
"""
import pytest

from speakhired.agents import core
from speakhired.engines.delivery import delivery_metrics
from speakhired.reasoning.lev import LevClient
from speakhired.reasoning.questions import LEVELS, lev_questions, level_to_five, level_to_unit, resume_questions
from speakhired.schemas import Question
from speakhired.config import Settings


def check_question(name: str, q: dict) -> None:
    assert q["type"] in ("noul", "choice", "score"), name
    crit = q.get("criteria")
    if q["type"] == "score":
        assert isinstance(crit, list) and 2 <= len(crit) <= 10, f"{name}: score criteria must be a list of 2-10 levels"
    elif q["type"] == "choice":
        assert isinstance(crit, dict) and len(crit) >= 2, f"{name}: choice needs a dict of >= 2 options"
    else:
        assert crit is None or (isinstance(crit, dict) and set(crit) <= {"true", "false"}), f"{name}: bad noul criteria"


def test_interview_questions_match_the_lev_schema():
    qs = lev_questions(["partitions", "offsets", "ordering"])
    assert {"answered", "next_action", "relevance", "correctness", "depth", "structure", "specificity", "kp_0", "kp_2"} <= set(qs)
    for name, q in qs.items():
        check_question(name, q)


def test_resume_questions_match_the_lev_schema():
    qs = resume_questions()
    assert set(qs) == {"has_summary", "action_verbs", "quantified", "clarity", "specific_tech"}
    for name, q in qs.items():
        check_question(name, q)


def test_score_levels_convert_from_lev_index_to_the_scales_we_show():
    assert len(LEVELS) == 5
    assert [level_to_five(x) for x in (0, 0.4, 1.6, 2.0, 3.6, 4)] == [1, 1, 3, 3, 5, 5]
    assert level_to_unit(0) == 0 and level_to_unit(4) == 1 and level_to_unit(2) == 0.5 and level_to_unit(9) == 1 and level_to_unit(-1) == 0


class FakeLev(LevClient):
    async def decide(self, state, questions):
        for name, q in questions.items():
            check_question(name, q)  # the request itself must be valid
        scored = {d: {"score": 3.6, "confidence": 0.8, "probabilities": {}, "legend": {}} for d in ("relevance", "correctness", "depth", "structure", "specificity")}
        return {**scored, "answered": {"noul": 0.9}, "next_action": {"choice": "harder", "probabilities": {}, "confidence": 0.7}, "kp_0": {"noul": 0.8}, "kp_1": {"noul": 0.1}}


async def test_interview_scoring_reads_lev_answers_on_the_right_scale():
    q = Question(id="1", text="What is a consumer group?", key_points=["partitions", "offsets"])
    ev = await core.evaluate(None, FakeLev(Settings(lev_mode="http", lev_url="http://127.0.0.1:8000")), q, "A consumer group shares partitions.", delivery_metrics("x", 1))
    assert ev.judge == "lev" and set(ev.scores.values()) == {5} and ev.covered_points == ["partitions"] and ev.next_action == "harder"


@pytest.mark.parametrize("url, mode, where", [
    ("http://127.0.0.1:8000", "http", "this_computer"), ("http://localhost:8000", "http", "this_computer"), ("http://[::1]:8000", "http", "this_computer"),
    ("http://192.168.1.20:8000", "http", "network"), ("http://lab-pc.local:8000", "http", "network"), ("http://box.tailnet.ts.net:8000", "http", "network"),
    ("https://me--lev.modal.run", "http", "internet"), ("http://127.0.0.1:8000", "off", "off"),
])
def test_lev_location_is_reported_honestly(url, mode, where):
    assert LevClient(Settings(lev_mode=mode, lev_url=url)).location == where
