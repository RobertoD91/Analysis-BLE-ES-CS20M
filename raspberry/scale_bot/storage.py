"""SQLite store of the measurements, with their Telegram delivery state."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY,
    received_at REAL NOT NULL,   -- Unix time
    mac TEXT NOT NULL,
    weight_kg REAL NOT NULL,
    counter INTEGER NOT NULL,
    state INTEGER NOT NULL,
    frame TEXT NOT NULL,         -- raw frame in hex
    sent_at REAL                 -- NULL until delivered to Telegram
)
"""


class Storage:
    def __init__(self, path):
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute(SCHEMA)

    def add(self, frame, received_at):
        with self._db:
            cur = self._db.execute(
                "INSERT INTO measurements (received_at, mac, weight_kg, counter, state, frame) VALUES (?, ?, ?, ?, ?, ?)",
                (received_at, frame.mac, frame.weight_kg, frame.counter, frame.state, frame.raw.hex()),
            )
        return cur.lastrowid

    def last_key(self):
        row = self._db.execute("SELECT mac, counter, weight_kg FROM measurements ORDER BY id DESC LIMIT 1").fetchone()
        return (row["mac"], row["counter"], row["weight_kg"]) if row else None

    def previous(self, measurement_id):
        return self._db.execute(
            "SELECT * FROM measurements WHERE id < ? ORDER BY id DESC LIMIT 1", (measurement_id,)
        ).fetchone()

    def unsent(self):
        return self._db.execute("SELECT * FROM measurements WHERE sent_at IS NULL ORDER BY id").fetchall()

    def mark_sent(self, measurement_id, sent_at):
        with self._db:
            self._db.execute("UPDATE measurements SET sent_at = ? WHERE id = ?", (sent_at, measurement_id))

    def latest(self, limit):
        return self._db.execute("SELECT * FROM measurements ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
