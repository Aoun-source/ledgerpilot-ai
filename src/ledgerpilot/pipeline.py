"""One case end to end: extract -> validate -> rules -> agent -> act -> audit.

Nothing here fakes a service. If Evolus or the AMD-hosted agent is unreachable
the case is marked as an error (or falls back to the stricter rule route) and
the reason is shown; it is never silently approved.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from .agent_client import AgentVerdict, ClerkAgent
from .audit import AuditLog
from .config import Settings
from .evolus_client import EvolusClient, EvolusError
from .fraud import load_vendor_master, mask
from .rules import evaluate, final_route
from .schemas import (
    Discrepancy,
    GoodsReceipt,
    Invoice,
    PastInvoice,
    PurchaseOrder,
    Route,
)

DOC_KINDS = ("po", "grn", "invoice")
MODELS = {"po": PurchaseOrder, "grn": GoodsReceipt, "invoice": Invoice}

Progress = Callable[[str], None]


@dataclass
class CaseResult:
    label: str
    route: Route
    rule_route: Optional[Route] = None
    agent: Optional[AgentVerdict] = None
    discrepancies: list[Discrepancy] = field(default_factory=list)
    money_at_risk: Decimal = Decimal("0")
    extracted: dict[str, Any] = field(default_factory=dict)
    email_draft: str = ""
    workflow_execution_id: Optional[str] = None
    timings: dict[str, float] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    audit_id: Optional[int] = None
    steps: list[dict[str, Any]] = field(default_factory=list)  # timeline shown in the UI

    def step(self, name: str, where: str, seconds: float, ok: bool = True, note: str = "") -> None:
        self.steps.append({"step": name, "where": where, "seconds": round(seconds, 2), "ok": ok, "note": note})


def unwrap(data: Any) -> dict[str, Any]:
    """Extractors may wrap output ({"data": {...}}, {"result": ...}, a one-item list, a JSON string)."""
    for _ in range(4):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return {}
        elif isinstance(data, list) and len(data) == 1:
            data = data[0]
        elif isinstance(data, dict) and len(data) == 1 and next(iter(data)) in {"data", "result", "output", "json"}:
            data = next(iter(data.values()))
        else:
            break
    return data if isinstance(data, dict) else {}


def load_history(settings: Settings) -> list[PastInvoice]:
    path = Path(settings.history_path)
    if not path.exists():
        return []
    return [PastInvoice(**h) for h in json.loads(path.read_text())]


class Pipeline:
    def __init__(self, settings: Settings, audit: AuditLog | None = None):
        settings.require()
        self.s = settings
        self.evolus = EvolusClient(settings)
        self.agent = ClerkAgent(settings)
        self.audit = audit or AuditLog(settings.audit_db)
        self.vendors = load_vendor_master(settings.vendor_master_path)
        self.extractor_ids = {"po": settings.extractor_po_id, "grn": settings.extractor_grn_id,
                              "invoice": settings.extractor_invoice_id}

    # ------------------------------------------------------------------
    def run(self, docs: dict[str, tuple[str, bytes]], label: str = "",
            progress: Progress = lambda _msg: None, start_workflow: bool = True) -> CaseResult:
        res = CaseResult(label=label, route=Route.ERROR)
        t0 = time.perf_counter()
        try:
            parsed = self._extract(docs, res, progress)
            po, grn, inv = parsed["po"], parsed["grn"], parsed["invoice"]

            progress("Running three-way match and fraud checks (Python, Decimal)")
            t = time.perf_counter()
            history = load_history(self.s) + self.audit.history()
            decision = evaluate(po, grn, inv, self.vendors, history, self.s.price_tolerance)
            res.rule_route, res.discrepancies = decision.route, decision.discrepancies
            res.money_at_risk = decision.money_at_risk
            res.timings["rules_s"] = time.perf_counter() - t
            res.step("Three-way match + fraud checks", "Python (Decimal)", res.timings["rules_s"],
                     note=f"{len(decision.discrepancies)} finding(s)")

            progress("Asking the LedgerPilot agent (open model on AMD MI300X via Evolus)")
            res.agent = self._ask_agent(po, grn, inv, decision, res)
            res.route = final_route(decision.route, res.agent.route if res.agent else None)

            if res.route in (Route.HOLD, Route.FRAUD):
                progress("Drafting the follow-up email (Evolus AI Tool)")
                res.email_draft = self._draft_email(inv, res)

            if start_workflow and self.s.workflow_id:
                progress("Starting the Exception routing workflow (Evolus)")
                res.workflow_execution_id = self._start_workflow(inv, res)
        except _CaseError as exc:
            res.route, res.error = Route.ERROR, str(exc)
        except Exception as exc:  # noqa: BLE001 - a case must never crash the app or be silently approved
            res.route, res.error = Route.ERROR, f"Unexpected error ({type(exc).__name__}: {str(exc)[:200]}). A person must process this invoice."
        res.timings["total_s"] = time.perf_counter() - t0
        try:
            res.audit_id = self._record(res)
        except Exception as exc:  # noqa: BLE001
            res.trace["audit_error"] = f"{type(exc).__name__}: {exc}"[:300]
        return res

    # ------------------------------------------------------------------ steps
    def _extract(self, docs, res: CaseResult, progress: Progress) -> dict[str, Any]:
        out = {}
        for kind in DOC_KINDS:
            if kind not in docs:
                raise _CaseError(f"Missing document: {kind}")
            name, blob = docs[kind]
            if not blob:
                raise _CaseError(f"The {kind} file is empty. Upload it again.")
            progress(f"Extracting {kind.upper()} with Evolus document extractor")
            t = time.perf_counter()
            try:
                result = self.evolus.extract(self.extractor_ids[kind], name, blob)
            except EvolusError as exc:
                res.step(f"Extract {kind.upper()}", "Evolus extractor", time.perf_counter() - t, ok=False, note=str(exc)[:120])
                raise _CaseError(f"Could not read the {kind} document ({exc}). A person must process it.") from exc
            res.timings[f"extract_{kind}_s"] = time.perf_counter() - t
            res.step(f"Extract {kind.upper()}", "Evolus extractor", res.timings[f"extract_{kind}_s"])
            res.trace[f"extract_{kind}"] = {"execution_id": result.execution_id, "audit_id": result.audit_id}
            data = unwrap(result.data)
            res.extracted[kind] = data
            if not data:
                raise _CaseError(f"The {kind} document produced no readable data. A person must process it.")
            try:
                out[kind] = MODELS[kind](**data)
            except ValidationError as exc:
                raise _CaseError(f"The {kind} data failed validation: {exc.errors()[0]['msg']}") from exc
        return out

    def _ask_agent(self, po, grn, inv, decision, res: CaseResult) -> Optional[AgentVerdict]:
        inv_view = inv.model_dump(mode="json")
        inv_view["bank_iban"] = mask(inv.bank_iban)  # the agent never needs the full account number
        case = {
            "purchase_order": po.model_dump(mode="json"),
            "goods_received_note": grn.model_dump(mode="json"),
            "invoice": inv_view,
            "discrepancies": [d.as_row() for d in decision.discrepancies],
            "money_at_risk": str(decision.money_at_risk),
            "rule_route": decision.route.value,
        }
        try:
            verdict = self.agent.review(case)
        except Exception as exc:  # noqa: BLE001
            res.trace["agent_error"] = f"{type(exc).__name__}: {exc}"[:300]
            res.step("Agent review", "Evolus agent on AMD MI300X", 0, ok=False, note="unreachable: rule route used")
            return None
        res.timings["agent_s"] = verdict.latency_s
        res.step("Agent review", "Evolus agent on AMD MI300X", verdict.latency_s, ok=verdict.parsed,
                 note=f"route {verdict.route.value}" if verdict.route else "reply not understood: rule route used")
        res.trace["agent"] = {"conversation_id": verdict.conversation_id, "parsed": verdict.parsed}
        return verdict

    def _draft_email(self, inv: Invoice, res: CaseResult) -> str:
        bullets = "\n".join(f"- {d.message}" for d in res.discrepancies)
        if res.route is Route.FRAUD:
            facts = (f"Internal alert to the finance manager. Payment for invoice {inv.invoice_number} from "
                     f"{inv.supplier_name or 'the supplier'} ({inv.supplier_id}), total {inv.total} {inv.currency}, is blocked "
                     f"as possible fraud. Findings:\n{bullets}\nAsk them to verify with the supplier by phone "
                     f"using the contact on file, not details printed on the invoice.")
        else:
            question = res.agent.supplier_question if res.agent and res.agent.supplier_question else ""
            facts = (f"To {inv.supplier_name or 'the supplier'}, accounts receivable. Our ref: PO {inv.po_number}. Your invoice "
                     f"{inv.invoice_number} dated {inv.invoice_date}, total {inv.total} {inv.currency}, is on hold. "
                     f"Findings:\n{bullets}\n{question}\nAsk for a credit note or corrected invoice.")
        t = time.perf_counter()
        try:
            draft = self.evolus.draft_supplier_email(facts)
        except EvolusError as exc:
            res.trace["email_error"] = str(exc)
            res.step("Draft email", "Evolus AI Tool", time.perf_counter() - t, ok=False, note=str(exc)[:120])
            return ""
        res.timings["email_s"] = time.perf_counter() - t
        res.step("Draft email", "Evolus AI Tool", res.timings["email_s"])
        return draft

    def _start_workflow(self, inv: Invoice, res: CaseResult) -> Optional[str]:
        params = {"route": res.route.value, "invoice_number": inv.invoice_number or "",
                  "supplier_id": inv.supplier_id or "", "money_at_risk": str(res.money_at_risk),
                  "codes": ",".join(sorted({d.code for d in res.discrepancies}))}
        summary = res.agent.explanation if res.agent else "; ".join(d.message for d in res.discrepancies)
        t = time.perf_counter()
        try:
            exec_id = self.evolus.start_workflow(f"LedgerPilot case {res.label}: {res.route.value}. {summary}", params)
        except EvolusError as exc:
            res.trace["workflow_error"] = str(exc)
            res.step("Start routing workflow", "Evolus workflow", time.perf_counter() - t, ok=False, note=str(exc)[:120])
            return None
        res.timings["workflow_start_s"] = time.perf_counter() - t
        res.step("Start routing workflow", "Evolus workflow", res.timings["workflow_start_s"], note=f"execution {exec_id}")
        return exec_id

    def _record(self, res: CaseResult) -> int:
        inv = res.extracted.get("invoice", {}) or {}
        return self.audit.record({
            "label": res.label,
            "supplier_id": inv.get("supplier_id"), "invoice_number": inv.get("invoice_number"),
            "invoice_date": inv.get("invoice_date"), "total": str(inv.get("total")) if inv.get("total") is not None else None,
            "currency": inv.get("currency"),
            "rule_route": res.rule_route.value if res.rule_route else None,
            "agent_route": res.agent.route.value if res.agent and res.agent.route else None,
            "final_route": res.route.value, "money_at_risk": str(res.money_at_risk),
            "explanation": res.agent.explanation if res.agent else None,
            "evidence": res.agent.evidence if res.agent else [],
            "email_draft": res.email_draft,
            "discrepancies": [d.as_row() for d in res.discrepancies],
            "extracted": res.extracted, "timings": res.timings, "trace": res.trace,
            "workflow_execution_id": res.workflow_execution_id, "error": res.error,
        })


class _CaseError(RuntimeError):
    pass


def load_case_folder(folder: str | Path) -> dict[str, tuple[str, bytes]]:
    folder = Path(folder)
    return {k: (f"{k}.pdf", (folder / f"{k}.pdf").read_bytes()) for k in DOC_KINDS}
