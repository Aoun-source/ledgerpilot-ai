"""Save and replay the output of real live runs for the app's demo mode.

A recording is written only from a CaseResult that the real pipeline produced
against Evolus and the AMD-hosted model (eval/run_eval.py, or the "Save for demo
mode" button after a live check). The app always labels a replayed result as
recorded, with the time and model it was recorded with; it is never shown as live.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from .agent_client import AgentVerdict
from .pipeline import CaseResult
from .schemas import Discrepancy, Route

FORMAT = 1


def to_record(res: CaseResult, case: str, model: Optional[str], source: str) -> dict[str, Any]:
    agent = None
    if res.agent:
        a = res.agent
        agent = {"route": a.route.value if a.route else None, "explanation": a.explanation, "evidence": a.evidence,
                 "supplier_question": a.supplier_question, "raw": a.raw, "conversation_id": a.conversation_id,
                 "latency_s": a.latency_s, "parsed": a.parsed}
    return {
        "format": FORMAT,
        "recorded": {"case": case, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "model": model, "source": source},
        "result": {
            "label": res.label, "route": res.route.value,
            "rule_route": res.rule_route.value if res.rule_route else None,
            "agent": agent,
            "discrepancies": [d.model_dump(mode="json") for d in res.discrepancies],
            "money_at_risk": str(res.money_at_risk), "extracted": res.extracted, "email_draft": res.email_draft,
            "workflow_execution_id": res.workflow_execution_id, "timings": res.timings, "trace": res.trace,
            "error": res.error, "steps": res.steps,
        },
    }


def from_record(data: dict[str, Any]) -> tuple[CaseResult, dict[str, Any]]:
    r = data["result"]
    agent = None
    if r.get("agent"):
        a = r["agent"]
        agent = AgentVerdict(route=Route(a["route"]) if a.get("route") else None, explanation=a.get("explanation", ""),
                             evidence=list(a.get("evidence") or []), supplier_question=a.get("supplier_question", ""),
                             raw=a.get("raw", ""), conversation_id=a.get("conversation_id"),
                             latency_s=float(a.get("latency_s") or 0), parsed=bool(a.get("parsed")))
    res = CaseResult(
        label=r["label"], route=Route(r["route"]),
        rule_route=Route(r["rule_route"]) if r.get("rule_route") else None, agent=agent,
        discrepancies=[Discrepancy(**d) for d in r.get("discrepancies", [])],
        money_at_risk=Decimal(r.get("money_at_risk") or "0"), extracted=r.get("extracted") or {},
        email_draft=r.get("email_draft", ""), workflow_execution_id=r.get("workflow_execution_id"),
        timings=r.get("timings") or {}, trace=r.get("trace") or {}, error=r.get("error"), steps=r.get("steps") or [],
    )
    return res, data["recorded"]


def save(directory: Path, res: CaseResult, case: str, model: Optional[str], source: str) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{case}.json"
    path.write_text(json.dumps(to_record(res, case, model, source), indent=2, default=str))
    return path


def load(directory: Path, case: str) -> Optional[tuple[CaseResult, dict[str, Any]]]:
    path = Path(directory) / f"{case}.json"
    if not path.exists():
        return None
    try:
        return from_record(json.loads(path.read_text()))
    except (ValueError, KeyError, TypeError):
        return None  # a damaged recording is skipped, never half-shown


def available(directory: Path) -> list[str]:
    directory = Path(directory)
    return sorted(p.stem for p in directory.glob("*.json")) if directory.exists() else []
