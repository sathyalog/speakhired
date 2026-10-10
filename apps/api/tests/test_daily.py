import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from speakhired import main  # noqa: E402
from speakhired.engines import daily  # noqa: E402
from speakhired.engines.srs import Card, combined_grade, is_due, review  # noqa: E402
from speakhired.store.progress import ProgressStore  # noqa: E402

TODAY = date(2026, 10, 9)


def fresh_store():
    return ProgressStore(Path(tempfile.mkdtemp()) / "p.sqlite")


# ---------- content ----------
def test_content_is_complete_and_consistent():
    items = daily.items()
    assert len(items) >= 60 and len({i["id"] for i in items}) == len(items)
    for lv in daily.LEVEL_IDS:
        assert len(daily.level_items(lv)) >= daily.DAILY_SIZE, f"{lv} needs a full daily set"
    for i in items:
        assert i["kind"] in ("abbreviation", "term", "phrase") and i["text"] and i["meaning"] and i["prompt"]
        assert daily.uses_term(i["example"], i), f"example for {i['id']} does not use the term"
        assert i["example"][-1] in ".?!"


def test_daily_set_is_15_items_with_no_duplicates_for_every_level():
    for lv in daily.LEVEL_IDS:
        picked = daily.choose_today({}, TODAY, lv)
        assert len(picked) == daily.DAILY_SIZE and len({i["id"] for i in picked}) == daily.DAILY_SIZE
        assert all(i["level"] == lv for i in picked)


def test_levels_do_not_mix_and_are_stored_separately():
    counts = {lv: {i["id"] for i in daily.level_items(lv)} for lv in daily.LEVEL_IDS}
    assert not (counts["foundation"] & counts["expert"]) and not (counts["professional"] & counts["expert"])
    assert daily.item("blast-radius")["level"] == "expert" and daily.item("eod")["level"] == "foundation"
    with pytest.raises(ValueError):
        daily.choose_today({}, TODAY, "guru")


def test_due_items_come_back_first_and_future_items_wait():
    overdue = Card(item_id="pr", interval=2, reps=2, due=(TODAY - timedelta(days=3)).isoformat())
    later = Card(item_id="eod", interval=5, reps=2, due=(TODAY + timedelta(days=4)).isoformat())
    picked = [i["id"] for i in daily.choose_today({"pr": overdue, "eod": later}, TODAY, "foundation")]
    assert picked[0] == "pr"                  # overdue comes first
    assert "eod" not in picked                # not due yet, and there are plenty of new items to fill the set


# ---------- spaced repetition ----------
def test_good_answers_space_reviews_further_apart():
    c = Card(item_id="x")
    c = review(c, "good", TODAY)
    assert c.interval == 1 and c.reps == 1
    c = review(c, "good", TODAY)
    assert c.interval == 3
    c2 = review(c, "good", TODAY)
    assert c2.interval > 3 and c2.reps == 3


def test_forgetting_resets_and_counts_lapses():
    c = review(review(Card(item_id="x"), "good", TODAY), "good", TODAY)
    c = review(c, "again", TODAY)
    assert c.interval == 1 and c.reps == 0 and c.lapses == 1 and c.ease < 2.5


def test_easy_grows_faster_than_good_and_ease_stays_above_floor():
    base = review(review(Card(item_id="x"), "good", TODAY), "good", TODAY)
    assert review(base, "easy", TODAY).interval > review(base, "good", TODAY).interval
    c = Card(item_id="x", ease=1.3)
    for _ in range(5):
        c = review(c, "again", TODAY)
    assert c.ease >= 1.3


def test_due_dates_and_bad_grades():
    c = review(Card(item_id="x"), "good", TODAY)
    assert c.due == (TODAY + timedelta(days=1)).isoformat() and not is_due(c, TODAY) and is_due(c, TODAY + timedelta(days=1))
    with pytest.raises(ValueError):
        review(Card(item_id="x"), "meh", TODAY)
    assert combined_grade("good", "hard") == "hard" and combined_grade("again", "easy") == "again" and combined_grade() == "good"


# ---------- scoring ----------
@pytest.mark.parametrize("heard", ["E O D", "e.o.d.", "EOD", "eod"])
def test_repeat_accepts_letters_said_one_by_one(heard):
    assert daily.score_repeat(daily.item("eod"), heard)[0] == "good"


def test_repeat_grades_close_and_far_attempts():
    it = daily.item("circle-back")
    assert daily.score_repeat(it, "I'll circle back")[0] == "good"
    assert daily.score_repeat(it, "I will circle bac")[0] in ("good", "hard")
    assert daily.score_repeat(it, "")[0] == "again"
    assert daily.score_repeat(it, "the weather is nice today")[0] == "again"


@pytest.mark.parametrize("answer, grade", [
    ("I will send the report by EOD.", "good"),
    ("I will send the report by the end of day.", "good"),
    ("I will send the report tomorrow morning.", "again"),
    ("", "again"),
])
def test_use_step_checks_the_term_is_there(answer, grade):
    assert daily.score_use(daily.item("eod"), answer)[0] == grade


def test_use_step_shows_a_better_phrase_when_one_exists():
    it = daily.item("circle-back")
    _, _, better = daily.score_use(it, "I will check later")
    assert better and "circle back" in better.lower()


def test_term_must_be_a_whole_word():
    it = daily.item("eod")
    assert not daily.uses_term("We will hit the period tomorrow", it)   # 'eod' is not inside another word


# ---------- endpoints ----------
@pytest.fixture
def client(monkeypatch):
    main.progress = fresh_store()
    return TestClient(main.app)


def test_today_returns_15_items_and_progress(client):
    body = client.get("/api/daily/today").json()
    assert len(body["items"]) == 15 and body["progress"]["total"] == len(daily.level_items("professional")) and body["streak"] == 0


def test_level_choice_is_remembered_and_changes_the_set(client):
    assert client.get("/api/daily/levels").json()["current"] == "professional"
    r = client.post("/api/daily/level", json={"level": "expert"}).json()
    assert r["current"] == "expert" and {lv["id"] for lv in r["levels"]} == set(daily.LEVEL_IDS)
    today = client.get("/api/daily/today").json()
    assert today["level"] == "expert" and all(i["level"] == "expert" for i in today["items"])
    assert client.post("/api/daily/level", json={"level": "guru"}).status_code == 400


def test_attempt_flow_schedules_once_per_day(client):
    r = client.post("/api/daily/attempt", json={"item_id": "eod", "step": "repeat", "transcript": "E O D"}).json()
    assert r["grade"] == "good" and r["next"] == "use"
    r = client.post("/api/daily/attempt", json={"item_id": "eod", "step": "use", "transcript": "I'll send it by EOD."}).json()
    assert r["item_grade"] == "good" and r["next_review_days"] == 1
    first_due = main.progress.cards()["eod"].due
    client.post("/api/daily/attempt", json={"item_id": "eod", "step": "use", "transcript": "by EOD again."})
    assert main.progress.cards()["eod"].due == first_due     # a second attempt the same day does not reschedule


def test_failed_repeat_pulls_the_item_into_the_use_grade(client):
    client.post("/api/daily/attempt", json={"item_id": "eod", "step": "repeat", "transcript": "something else"})
    r = client.post("/api/daily/attempt", json={"item_id": "eod", "step": "use", "transcript": "by EOD"}).json()
    assert r["item_grade"] == "again" and r["next_review_days"] == 1


def test_non_english_answers_are_refused(client):
    r = client.post("/api/daily/attempt", json={"item_id": "eod", "step": "use", "transcript": "mujhe kya karna hai matlab nahi pata"})
    assert r.status_code == 422 and "English" in r.json()["detail"]


def test_bad_requests(client):
    assert client.post("/api/daily/attempt", json={"item_id": "nope", "step": "repeat"}).status_code == 404
    assert client.post("/api/daily/attempt", json={"item_id": "eod", "step": "dance"}).status_code == 400


def test_completed_items_are_shown_and_streak_counts(client):
    client.post("/api/daily/attempt", json={"item_id": "eod", "step": "use", "transcript": "by EOD"})
    client.post("/api/daily/level", json={"level": "foundation"})
    today = client.get("/api/daily/today").json()
    assert "eod" in today["done_today"] and today["streak"] == 1
    assert client.get("/api/daily/progress").json()["streak"] == 1
