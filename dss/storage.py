"""Append-only local scenario/run snapshots. No operational data are ingested implicitly."""

import json
from pathlib import Path
import sqlite3

from .serialization import canonical, fingerprint


class RunStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL, scenario_id TEXT NOT NULL, version INTEGER NOT NULL, mode TEXT NOT NULL, snapshot TEXT NOT NULL)")

    def save(self, run):
        if fingerprint(run["scenario"]) != run["scenario_fingerprint"]:
            raise ValueError("run scenario fingerprint does not match its snapshot")
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                               (run["run_id"], run["recorded_at_utc"], run["scenario"]["scenario_id"],
                                run["scenario"]["version"], run["mode"], canonical(run)))

    def list_runs(self):
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT run_id, recorded_at, scenario_id, version, mode FROM runs ORDER BY recorded_at DESC, run_id")]

    def load(self, run_id):
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT snapshot FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown run {run_id}")
        return json.loads(row[0])
