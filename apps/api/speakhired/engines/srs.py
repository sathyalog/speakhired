"""Spaced repetition: when to show a card again. Pure functions so the schedule is easy to test.

A card grade is one of: "again" (forgot), "hard" (got it with effort), "good", "easy".
"""
from dataclasses import dataclass
from datetime import date, timedelta

GRADES = ("again", "hard", "good", "easy")
MIN_EASE = 1.3


@dataclass
class Card:
    item_id: str
    ease: float = 2.5
    interval: int = 0       # days until the next review
    reps: int = 0           # successful reviews in a row
    lapses: int = 0         # times forgotten
    due: str = ""           # ISO date; "" means never seen


def review(card: Card, grade: str, today: date) -> Card:
    if grade not in GRADES:
        raise ValueError(f"unknown grade {grade!r}")
    c = Card(**card.__dict__)
    if grade == "again":
        c.lapses += 1
        c.reps = 0
        c.interval = 1
        c.ease = max(MIN_EASE, c.ease - 0.2)
    else:
        if c.reps == 0:
            c.interval = 1
        elif c.reps == 1:
            c.interval = 3 if grade != "hard" else 2
        elif grade == "hard":
            c.interval = max(c.interval + 1, round(c.interval * 1.2))
            c.ease = max(MIN_EASE, c.ease - 0.15)
        elif grade == "good":
            c.interval = max(c.interval + 1, round(c.interval * c.ease))
        else:  # easy
            c.interval = max(c.interval + 2, round(c.interval * c.ease * 1.3))
            c.ease += 0.15
        c.reps += 1
    c.due = (today + timedelta(days=c.interval)).isoformat()
    return c


def is_due(card: Card, today: date) -> bool:
    return bool(card.due) and date.fromisoformat(card.due) <= today


def combined_grade(*grades: str) -> str:
    """The item's grade for one day: the weakest step decides."""
    order = {"again": 0, "hard": 1, "good": 2, "easy": 3}
    return min(grades, key=lambda g: order[g]) if grades else "good"
