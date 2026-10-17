"""Run every sample case through the REAL pipeline and score it against ground truth.

    python eval/run_eval.py --label "DeepSeek-V4-Flash"

Uses a separate audit database so earlier runs don't trigger duplicate alerts.
Writes docs/evaluation.md and docs/evaluation.json, and saves each case's live
output to data/recordings/ for the app's demo mode (skip with --no-record).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ledgerpilot import recording  # noqa: E402
from ledgerpilot.agent_client import model_health  # noqa: E402
from ledgerpilot.audit import AuditLog  # noqa: E402
from ledgerpilot.config import load_settings  # noqa: E402
from ledgerpilot.pipeline import Pipeline, load_case_folder  # noqa: E402

KIND = {"approve_for_payment": "Clean invoice", "hold_for_review": "Billing error (hold)",
        "escalate_fraud": "Fraud signal (block)", "processing_error": "Unreadable document"}


def scenario(truth: dict) -> str:
    """Case type for the per-type table: the expected route, split by the main finding."""
    codes = truth["expected_codes"]
    return KIND[truth["expected_route"]] + (f": {codes[0]}" if codes else "")

FIELDS = {
    "invoice": ["invoice_number", "invoice_date", "po_number", "supplier_id", "currency", "bank_iban", "subtotal", "tax", "total"],
    "po": ["po_number", "supplier_id", "currency"],
    "grn": ["grn_number", "po_number"],
}


def norm(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace(" ", "").upper()
    try:
        return str(float(s))
    except ValueError:
        return s


def field_scores(truth: dict, extracted: dict) -> tuple[int, int]:
    good = total = 0
    for kind, names in FIELDS.items():
        t, e = truth.get(kind) or {}, extracted.get(kind) or {}
        if not t:
            continue
        for n in names:
            total += 1
            good += norm(t.get(n)) == norm(e.get(n))
        for tl, el in zip(t.get("lines", []), e.get("lines", []) or [], strict=False):
            for n in ("sku", "qty", "unit_price", "qty_received", "line_total"):
                if n in tl:
                    total += 1
                    good += norm(tl.get(n)) == norm(el.get(n))
        total += max(0, len(t.get("lines", [])) - len(e.get("lines", []) or [])) * 3
    return good, total


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="")
    ap.add_argument("--cases", nargs="*", help="case folder names, default all")
    ap.add_argument("--no-record", action="store_true", help="don't save outputs for demo mode")
    ap.add_argument("--out", type=Path, default=ROOT / "docs", help="where evaluation.md/.json are written")
    ap.add_argument("--audit-db", type=Path, default=ROOT / "eval" / "eval_audit.db")
    a = ap.parse_args(argv)
    s = load_settings()
    s.audit_db = a.audit_db
    audit = AuditLog(s.audit_db)
    audit.reset()
    pipe = Pipeline(s, audit)
    health = model_health(s)
    model = health.get("weights") if health["ok"] else None
    print(f"AMD endpoint ({s.model_where}): {'online, ' + str(model) if health['ok'] else 'NOT reachable: ' + health['detail']}")

    folders = sorted((ROOT / "data" / "samples").glob("case_*"))
    if a.cases:
        folders = [f for f in folders if f.name in a.cases]
    rows = []
    for f in folders:
        truth = json.loads((f / "truth.json").read_text())
        res = pipe.run(load_case_folder(f), label=f.name, start_workflow=True)
        if not a.no_record:
            recording.save(s.recordings_dir, res, f.name, model or s.amd_model, source=f"eval/run_eval.py {a.label}".strip())
        g, t = field_scores(truth, res.extracted)
        expected = truth["expected_route"]
        rows.append({
            "case": f.name, "type": scenario(truth), "description": truth["description"],
            "expected": expected, "got": res.route.value,
            "correct": res.route.value == expected,
            "codes_expected": truth["expected_codes"], "codes_got": sorted({d.code for d in res.discrepancies}),
            "agent_route": res.agent.route.value if res.agent and res.agent.route else None,
            "fields_correct": g, "fields_total": t, "latency_s": round(res.timings.get("total_s", 0), 2),
            "agent_s": round(res.timings.get("agent_s", 0), 2), "error": res.error,
        })
        print(f"{f.name}: expected {expected:22} got {res.route.value:22} {'OK' if rows[-1]['correct'] else 'MISS'}")

    clean = [r for r in rows if r["expected"] == "approve_for_payment"]
    problems = [r for r in rows if r["expected"] in ("hold_for_review", "escalate_fraud")]
    fields_ok, fields_all = sum(r["fields_correct"] for r in rows), sum(r["fields_total"] for r in rows)
    lat = sorted(r["latency_s"] for r in rows)
    summary = {
        "label": a.label, "model": model, "cases": len(rows),
        "false_approvals": sum(r["got"] == "approve_for_payment" and r["expected"] != "approve_for_payment" for r in rows),
        "p95_latency_s": lat[int(0.95 * (len(lat) - 1))],
        "routing_accuracy": sum(r["correct"] for r in rows) / len(rows),
        "exception_recall": sum(r["got"] != "approve_for_payment" for r in problems) / max(len(problems), 1),
        "false_alarm_rate": sum(r["got"] != "approve_for_payment" for r in clean) / max(len(clean), 1),
        "fraud_recall": sum(r["got"] == "escalate_fraud" for r in rows if r["expected"] == "escalate_fraud")
                        / max(sum(r["expected"] == "escalate_fraud" for r in rows), 1),
        "field_accuracy": fields_ok / max(fields_all, 1),
        "agent_agreement": sum(r["agent_route"] == r["expected"] for r in rows if r["agent_route"]) / max(sum(1 for r in rows if r["agent_route"]), 1),
        "median_latency_s": statistics.median(r["latency_s"] for r in rows),
        "median_agent_s": statistics.median(r["agent_s"] for r in rows if r["agent_s"]) if any(r["agent_s"] for r in rows) else None,
    }
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation.json").write_text(json.dumps({"summary": summary, "cases": rows}, indent=2))
    pct = lambda x: f"{x:.0%}"  # noqa: E731
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r)
    md = [f"# Evaluation{(' - ' + a.label) if a.label else ''}", "",
          f"{len(rows)} synthetic cases (data/samples), full pipeline: Evolus extractors -> Python rules -> agent on {s.model_where}.",
          f"Model reported by the AMD endpoint: {model or 'unknown (endpoint not reachable during the run)'}.", "",
          "| Metric | Result | Definition |", "| --- | --- | --- |",
          f"| False approvals | {summary['false_approvals']} of {len(problems) + sum(r['expected'] == 'processing_error' for r in rows)} "
          f"| problem or unreadable cases marked ready to pay |",
          f"| Routing accuracy | {pct(summary['routing_accuracy'])} | final route = expected route |",
          f"| Exception recall | {pct(summary['exception_recall'])} | problem cases not approved |",
          f"| Fraud recall | {pct(summary['fraud_recall'])} | fraud cases escalated as fraud |",
          f"| False alarms | {pct(summary['false_alarm_rate'])} | clean cases not approved |",
          f"| Field extraction accuracy | {pct(summary['field_accuracy'])} | extracted fields equal to ground truth |",
          f"| Agent agreement | {pct(summary['agent_agreement'])} | agent's own route = expected route |",
          f"| Median end-to-end latency | {summary['median_latency_s']} s | upload to decision |",
          f"| p95 end-to-end latency | {summary['p95_latency_s']} s | upload to decision |",
          f"| Median agent latency | {summary['median_agent_s']} s | {s.model_where} model via Evolus |", "",
          "## Accuracy by case type", "",
          "| Case type | Cases | Routed correctly |", "| --- | --- | --- |"]
    md += [f"| {t} | {len(rs)} | {sum(r['correct'] for r in rs)} of {len(rs)} |" for t, rs in sorted(by_type.items())]
    md += ["", "## Every case", "",
           "| Case | Scenario | Expected | Got | Codes found |", "| --- | --- | --- | --- | --- |"]
    md += [f"| {r['case']} | {r['description']} | {r['expected']} | {r['got']}{'' if r['correct'] else ' (miss)'} | {', '.join(r['codes_got'])} |" for r in rows]
    (out / "evaluation.md").write_text("\n".join(md) + "\n")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
