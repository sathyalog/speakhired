"""Daily English progress in the local database: one row per card, one row per attempt, one row per practised day."""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from ..config import get_settings
from ..engines.srs import Card


class ProgressStore:
    def __init__(self, path: Path | None = None):
        path = path or Path(get_settings().data_dir) / "speakhired.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS daily_cards (item_id TEXT PRIMARY KEY, ease REAL, interval INTEGER, reps INTEGER, lapses INTEGER, due TEXT);
            CREATE TABLE IF NOT EXISTS daily_attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, item_id TEXT, step TEXT, grade TEXT);
            CREATE TABLE IF NOT EXISTS daily_days (day TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS daily_settings (key TEXT PRIMARY KEY, value TEXT);
        """)

    def get_setting(self, key: str, default: str) -> str:
        row = self.db.execute("SELECT value FROM daily_settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO daily_settings VALUES (?,?)", (key, value))
        self.db.commit()

    def cards(self) -> dict[str, Card]:
        rows = self.db.execute("SELECT item_id, ease, interval, reps, lapses, due FROM daily_cards").fetchall()
        return {r[0]: Card(item_id=r[0], ease=r[1], interval=r[2], reps=r[3], lapses=r[4], due=r[5] or "") for r in rows}

    def save_card(self, c: Card) -> None:
        self.db.execute("INSERT OR REPLACE INTO daily_cards VALUES (?,?,?,?,?,?)", (c.item_id, c.ease, c.interval, c.reps, c.lapses, c.due))
        self.db.commit()

    def record(self, day: date, item_id: str, step: str, grade: str) -> None:
        self.db.execute("INSERT INTO daily_attempts (day, item_id, step, grade) VALUES (?,?,?,?)", (day.isoformat(), item_id, step, grade))
        self.db.execute("INSERT OR IGNORE INTO daily_days VALUES (?)", (day.isoformat(),))
        self.db.commit()

    def grades_today(self, day: date, item_id: str) -> dict[str, str]:
        """The latest grade for each step of this item today, so the 'use' step can combine them."""
        rows = self.db.execute("SELECT step, grade FROM daily_attempts WHERE day=? AND item_id=? ORDER BY id", (day.isoformat(), item_id)).fetchall()
        return dict(rows)

    def done_today(self, day: date) -> list[str]:
        """Items whose 'use' step was finished today, whether or not they are in today's set any more."""
        rows = self.db.execute("SELECT DISTINCT item_id FROM daily_attempts WHERE day=? AND step='use'", (day.isoformat(),)).fetchall()
        return [r[0] for r in rows]

    def streak(self, today: date) -> int:
        days = {r[0] for r in self.db.execute("SELECT day FROM daily_days").fetchall()}
        start = today if today.isoformat() in days else today - timedelta(days=1)
        n = 0
        while (start - timedelta(days=n)).isoformat() in days:
            n += 1
        return n
