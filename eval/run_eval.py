"""Run every sample case through the REAL pipeline and score it against ground truth.

    python eval/run_eval.py --label "Qwen2.5-32B"

Uses a separate audit database so earlier runs don't trigger duplicate alerts.
Writes docs/evaluation.md and docs/evaluation.json.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ledgerpilot.audit import AuditLog  # noqa: E402
from ledgerpilot.config import load_settings  # noqa: E402
from ledgerpilot.pipeline import Pipeline, load_case_folder  # noqa: E402

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="")
    ap.add_argument("--cases", nargs="*", help="case folder names, default all")
    a = ap.parse_args()
    s = load_settings()
    s.audit_db = ROOT / "eval" / "eval_audit.db"
    audit = AuditLog(s.audit_db)
    audit.reset()
    pipe = Pipeline(s, audit)

    folders = sorted((ROOT / "data" / "samples").glob("case_*"))
    if a.cases:
        folders = [f for f in folders if f.name in a.cases]
    rows = []
    for f in folders:
        truth = json.loads((f / "truth.json").read_text())
        res = pipe.run(load_case_folder(f), label=f.name, start_workflow=True)
        g, t = field_scores(truth, res.extracted)
        expected = truth["expected_route"]
        rows.append({
            "case": f.name, "description": truth["description"], "expected": expected, "got": res.route.value,
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
    summary = {
        "label": a.label, "cases": len(rows),
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
    out = ROOT / "docs"
    (out / "evaluation.json").write_text(json.dumps({"summary": summary, "cases": rows}, indent=2))
    pct = lambda x: f"{x:.0%}"  # noqa: E731
    md = [f"# Evaluation{(' - ' + a.label) if a.label else ''}", "",
          f"{len(rows)} synthetic cases (data/samples), full pipeline: Evolus extractors -> Python rules -> agent on AMD MI300X.", "",
          "| Metric | Result | Definition |", "| --- | --- | --- |",
          f"| Routing accuracy | {pct(summary['routing_accuracy'])} | final route = expected route |",
          f"| Exception recall | {pct(summary['exception_recall'])} | problem cases not approved |",
          f"| Fraud recall | {pct(summary['fraud_recall'])} | fraud cases escalated as fraud |",
          f"| False alarms | {pct(summary['false_alarm_rate'])} | clean cases not approved |",
          f"| Field extraction accuracy | {pct(summary['field_accuracy'])} | extracted fields equal to ground truth |",
          f"| Agent agreement | {pct(summary['agent_agreement'])} | agent's own route = expected route |",
          f"| Median end-to-end latency | {summary['median_latency_s']} s | upload to decision |",
          f"| Median agent latency | {summary['median_agent_s']} s | AMD-hosted model via Evolus |", "",
          "| Case | Scenario | Expected | Got | Codes found |", "| --- | --- | --- | --- | --- |"]
    md += [f"| {r['case']} | {r['description']} | {r['expected']} | {r['got']}{'' if r['correct'] else ' (miss)'} | {', '.join(r['codes_got'])} |" for r in rows]
    (out / "evaluation.md").write_text("\n".join(md) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
