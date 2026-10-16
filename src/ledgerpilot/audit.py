"""SQLite audit log: every case, every decision, every Evolus execution ID."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import PastInvoice

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    label TEXT,
    supplier_id TEXT, invoice_number TEXT, invoice_date TEXT, total TEXT, currency TEXT,
    rule_route TEXT, agent_route TEXT, final_route TEXT NOT NULL,
    money_at_risk TEXT,
    explanation TEXT, evidence TEXT, email_draft TEXT,
    discrepancies TEXT, extracted TEXT, timings TEXT, trace TEXT,
    workflow_execution_id TEXT, error TEXT,
    review_decision TEXT, review_note TEXT, reviewed_at TEXT
);
"""


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, row: dict[str, Any]) -> int:
        row = {k: (json.dumps(v, default=str) if isinstance(v, (dict, list)) else v) for k, v in row.items()}
        row.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._conn() as c:
            cur = c.execute(f"INSERT INTO cases ({cols}) VALUES ({marks})", list(row.values()))
            return int(cur.lastrowid)

    def review(self, case_id: int, decision: str, note: str = "") -> None:
        with self._conn() as c:
            c.execute("UPDATE cases SET review_decision=?, review_note=?, reviewed_at=? WHERE id=?",
                      (decision, note, datetime.now(timezone.utc).isoformat(timespec="seconds"), case_id))

    def all(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM cases ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def pending_review(self) -> list[dict[str, Any]]:
        """Every case waits for a person, clean ones included: a human approves every payment."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM cases WHERE review_decision IS NULL ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    def history(self) -> list[PastInvoice]:
        """Invoices already processed here count for duplicate detection."""
        with self._conn() as c:
            # Failed extractions and invoices a person rejected were never payable, so a
            # corrected resubmission must not be flagged as a duplicate of them.
            rows = c.execute("SELECT supplier_id, invoice_number, invoice_date, total, extracted FROM cases "
                             "WHERE invoice_number IS NOT NULL AND final_route != 'processing_error' "
                             "AND (review_decision IS NULL OR review_decision != 'rejected_by_reviewer')").fetchall()
        out = []
        for r in rows:
            row = dict(r)
            billed = _billed(row.pop("extracted"))
            try:
                out.append(PastInvoice(**row, **billed))
            except ValueError:
                try:  # unreadable lines must not hide the invoice from the duplicate check
                    out.append(PastInvoice(**row))
                except ValueError:
                    continue
        return out

    def reset(self) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM cases")


def _billed(extracted: str | None) -> dict[str, Any]:
    """PO number and lines of a logged invoice, so later invoices on the same PO can be added up."""
    try:
        inv = json.loads(extracted or "{}").get("invoice") or {}
        return {"po_number": inv.get("po_number"), "lines": inv.get("lines")}
    except (ValueError, AttributeError):
        return {}
