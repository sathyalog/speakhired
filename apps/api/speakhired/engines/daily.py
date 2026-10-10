"""Daily English for IT: picks today's items and scores each step. Content is bundled, so nothing is generated each day."""
import json
import re
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from .srs import Card, is_due

DAILY_SIZE = 15
REPEAT_GOOD, REPEAT_CLOSE = 0.85, 0.6
DEFAULT_LEVEL = "professional"
LEVELS = [
    {"id": "foundation", "label": "Foundation", "for": "Everyday workplace words. Good for students and new joiners."},
    {"id": "professional", "label": "Professional", "for": "Working in a team and with clients. The usual interview level."},
    {"id": "expert", "label": "Expert", "for": "10+ years: senior, architecture and leadership language."},
]
LEVEL_IDS = [lv["id"] for lv in LEVELS]


@lru_cache(maxsize=1)
def items() -> list[dict]:
    raw = json.loads((Path(__file__).resolve().parent.parent / "data" / "daily.json").read_text(encoding="utf-8"))
    return raw["items"]


def item(item_id: str) -> dict | None:
    return next((i for i in items() if i["id"] == item_id), None)


def level_items(level: str) -> list[dict]:
    return [i for i in items() if i.get("level", DEFAULT_LEVEL) == level]


def choose_today(cards: dict[str, Card], today: date, level: str = DEFAULT_LEVEL, size: int = DAILY_SIZE) -> list[dict]:
    """Items of this level: due reviews first (most overdue first), then new items in their bundled order, then the next-due items."""
    if level not in LEVEL_IDS:
        raise ValueError(f"unknown level {level!r}")
    in_level = {i["id"] for i in level_items(level)}
    due = sorted((c for c in cards.values() if c.item_id in in_level and is_due(c, today)), key=lambda c: c.due)
    seen = {c.item_id for c in cards.values()}
    new = [i for i in level_items(level) if i["id"] not in seen]
    later = sorted((c for c in cards.values() if c.item_id in in_level and not is_due(c, today)), key=lambda c: c.due)
    order = [c.item_id for c in due] + [i["id"] for i in new] + [c.item_id for c in later]
    picked, used = [], set()
    for iid in order:
        if iid in used or item(iid) is None:
            continue
        used.add(iid)
        picked.append(item(iid))
        if len(picked) == size:
            break
    return picked


def level_summary(cards: dict[str, Card]) -> list[dict]:
    out = []
    for lv in LEVELS:
        mine = level_items(lv["id"])
        ids = {i["id"] for i in mine}
        out.append({**lv, "total": len(mine), "learned": sum(1 for c in cards.values() if c.item_id in ids and c.reps >= 2),
                    "started": sum(1 for c in cards.values() if c.item_id in ids)})
    return out


def normalise(text: str) -> str:
    """Letters and digits only, lower case: 'E O D', 'e.o.d.' and 'EOD' all become 'eod'."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _phrase(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def variants(it: dict) -> set[str]:
    """Accepted spoken forms of the item, as space-separated words."""
    out = {_phrase(it["text"]), _phrase(it["text"].replace("'", "")), *(_phrase(a) for a in it.get("aliases", []))}
    if it["text"].isupper():
        out.add(" ".join(it["text"]).lower())            # abbreviations are often said letter by letter: "E O D"
    return {v for v in out if v}


def uses_term(answer: str, it: dict) -> bool:
    words = f" {_phrase(answer)} "
    return any(f" {v} " in words for v in variants(it))


def score_repeat(it: dict, heard: str) -> tuple[str, str]:
    """(grade, feedback) for saying the item back. Matches on letters only, so spelling and spacing do not matter."""
    target, got = normalise(it["text"]), normalise(heard)
    if not got:
        return "again", "I didn't hear anything. Try again and speak a little louder."
    if got == target or got in {normalise(v) for v in variants(it)}:
        return "good", "Clear and correct."
    ratio = SequenceMatcher(None, target, got).ratio()
    if ratio >= REPEAT_GOOD:
        return "good", f"Nearly there. The standard way to say it is '{it['text']}'."
    if ratio >= REPEAT_CLOSE:
        return "hard", f"Close. Say it as '{it['text']}', then try once more."
    return "again", f"That sounded different. Listen again and say '{it['text']}'."


def score_use(it: dict, answer: str) -> tuple[str, str, str]:
    """(grade, feedback, better phrasing) for using the item in a sentence."""
    better = (it.get("say_not") or {}).get("say") or it.get("example", "")
    if not answer.strip():
        return "again", "Write or say one sentence using the term.", better
    if uses_term(answer, it):
        return "good", f"Good, you used '{it['text']}' correctly.", better
    return "again", f"Use '{it['text']}' in your sentence. For example: \"{it['example']}\"", better


def progress_summary(cards: dict[str, Card], today: date, level: str = DEFAULT_LEVEL) -> dict:
    mine = {i["id"] for i in level_items(level)}
    learned = sum(1 for c in cards.values() if c.item_id in mine and c.reps >= 2)
    started = sum(1 for c in cards.values() if c.item_id in mine)
    due = sum(1 for c in cards.values() if c.item_id in mine and is_due(c, today))
    return {"level": level, "total": len(mine), "started": started, "learned": learned, "due_today": due}
