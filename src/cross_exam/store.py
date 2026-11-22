"""The scoreboard: one SQLite row per examination, keyed by the examined agent/model."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from cross_exam.models import Report

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    agent TEXT NOT NULL,
    examiner TEXT NOT NULL,
    task TEXT NOT NULL,
    criteria INTEGER NOT NULL,
    claims INTEGER NOT NULL,
    verified INTEGER NOT NULL,
    contradicted INTEGER NOT NULL,
    unverifiable INTEGER NOT NULL,
    skipped INTEGER NOT NULL,
    scope_creep INTEGER NOT NULL,
    overruled INTEGER NOT NULL,
    overclaim REAL NOT NULL,
    report TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_agent ON runs(agent, ts);
"""


class Board:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def add(self, report: Report, ts: float | None = None) -> int:
        s = report.scores
        cur = self.db.execute(
            "INSERT INTO runs (ts, agent, examiner, task, criteria, claims, verified, contradicted, unverifiable,"
            " skipped, scope_creep, overruled, overclaim, report) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                time.time() if ts is None else ts,
                report.agent,
                report.examiner,
                report.task,
                s.criteria,
                s.claims,
                s.verified,
                s.contradicted,
                s.unverifiable,
                s.skipped,
                s.scope_creep,
                s.overruled,
                s.overclaim,
                report.model_dump_json(),
            ),
        )
        self.db.commit()
        return int(cur.lastrowid or 0)

    def board(self) -> list[dict[str, Any]]:
        """Per agent: lie rate = contradicted / checkable claims, skip rate = skipped / criteria (pooled)."""
        rows = self.db.execute(
            "SELECT agent, COUNT(*) AS runs, SUM(claims) AS claims, SUM(verified) AS verified,"
            " SUM(contradicted) AS contradicted, SUM(unverifiable) AS unverifiable, SUM(criteria) AS criteria,"
            " SUM(skipped) AS skipped, SUM(scope_creep) AS scope_creep, SUM(overruled) AS overruled,"
            " AVG(overclaim) AS overclaim, MAX(ts) AS last FROM runs GROUP BY agent"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            checkable = d["verified"] + d["contradicted"]
            d["lie_rate"] = d["contradicted"] / checkable if checkable else None
            d["skip_rate"] = d["skipped"] / d["criteria"] if d["criteria"] else None
            d["overclaim"] = round(d["overclaim"] or 0.0, 4)
            out.append(d)
        out.sort(key=lambda d: (d["lie_rate"] is None, d["lie_rate"] or 0.0, d["skip_rate"] or 0.0, d["agent"]))
        return out

    def history(self, agent: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        sql = "SELECT id, ts, agent, examiner, task, claims, contradicted, skipped, overclaim FROM runs"
        args: tuple[Any, ...] = ()
        if agent:
            sql += " WHERE agent = ?"
            args = (agent,)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        return [dict(r) for r in self.db.execute(sql, (*args, limit)).fetchall()]

    def report(self, run_id: int) -> Report | None:
        row = self.db.execute("SELECT report FROM runs WHERE id = ?", (run_id,)).fetchone()
        return Report.model_validate(json.loads(row["report"])) if row else None
