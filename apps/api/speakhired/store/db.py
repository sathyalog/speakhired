import json
import sqlite3
import uuid
from pathlib import Path

from ..config import get_settings


class SessionStore:
    def __init__(self, path: Path | None = None):
        path = path or Path(get_settings().data_dir) / "speakhired.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, data TEXT NOT NULL)")

    def create(self, data: dict) -> str:
        sid = uuid.uuid4().hex[:12]
        self.save(sid, data)
        return sid

    def save(self, sid: str, data: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (sid, json.dumps(data)))
        self.db.commit()

    def get(self, sid: str) -> dict | None:
        row = self.db.execute("SELECT data FROM sessions WHERE id=?", (sid,)).fetchone()
        return json.loads(row[0]) if row else None
