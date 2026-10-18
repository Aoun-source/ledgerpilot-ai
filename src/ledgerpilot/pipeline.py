"""One case end to end: extract -> validate -> rules -> agent -> act -> audit.

Nothing here fakes a service. If Evolus or the AMD-hosted agent is unreachable
the case is marked as an error (or falls back to the stricter rule route) and
the reason is shown; it is never silently approved.
"""
from __future__ import annotations

import json
import re
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
from .fraud import _ACCOUNT, load_vendor_master, mask, mask_accounts  # noqa: F401 (_ACCOUNT kept for callers)
from .rules import confidence_reasons, evaluate, final_route, human_handoff
from .schemas import (
    Discrepancy,
    GoodsReceipt,
    Invoice,
    PastInvoice,
    PurchaseOrder,
    Route,
    strictest,
)

DOC_KINDS = ("po", "grn", "invoice")
MODELS = {"po": PurchaseOrder, "grn": GoodsReceipt, "invoice": Invoice}
DOC_NAMES = {"po": "purchase order", "grn": "delivery note", "invoice": "invoice"}

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

    @property
    def confidence_reasons(self) -> list[str]:
        return confidence_reasons(self.discrepancies)


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


# Names extractors use for our fields: camelCase (invoiceNumber) and plain-English synonyms (quantity).
_SYNONYMS = {"quantity": "qty", "quantity_billed": "qty", "quantity_ordered": "qty", "price": "unit_price",
             "amount": "line_total", "total_due": "total", "iban": "bank_iban"}
_GRN_SYNONYMS = {"qty": "qty_received", "quantity": "qty_received", "quantity_received": "qty_received"}


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()


def normalize(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Give extractor output our field names, so the checks and the screen read the same keys.
    A key that is already right is never overwritten by a synonym."""
    def fix(d: dict[str, Any], extra: dict[str, str]) -> dict[str, Any]:
        synonyms = {**_SYNONYMS, **extra}
        out: dict[str, Any] = {}
        renamed: list[tuple[str, Any]] = []
        for k, v in d.items():
            name = _snake(k)
            if name in synonyms:
                renamed.append((synonyms[name], v))
            else:
                out[name] = v
        for name, v in renamed:
            out.setdefault(name, v)
        return out
    data = fix(data, {})
    if isinstance(data.get("lines"), list):
        data["lines"] = [fix(ln, _GRN_SYNONYMS if kind == "grn" else {}) if isinstance(ln, dict) else ln
                         for ln in data["lines"]]
    return data


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
            decision = evaluate(po, grn, inv, self.vendors, history, self.s.price_tolerance, self.s.max_tax_rate)
            res.rule_route, res.discrepancies = decision.route, decision.discrepancies
            res.money_at_risk = decision.money_at_risk
            res.timings["rules_s"] = time.perf_counter() - t
            res.step("Three-way match + fraud checks", "Python (Decimal)", res.timings["rules_s"],
                     note=f"{len(decision.discrepancies)} finding(s)")

            progress(f"Asking the LedgerPilot agent (open model on {self.s.model_where} via Evolus)")
            res.agent = self._ask_agent(po, grn, inv, decision, res)
            agent_route = res.agent.route if res.agent else None
            res.route = final_route(decision.route, agent_route)
            handoff = human_handoff(decision.route, agent_route, agent_answered=res.agent is not None)
            res.discrepancies = res.discrepancies + handoff
            res.route = strictest([res.route] + [d.route for d in handoff])

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
            try:
                check_document(kind, name, blob)
            except _CaseError as exc:
                res.step(f"Check {kind.upper()} file", "Python", 0, ok=False, note=str(exc)[:120])
                raise
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
            data = normalize(kind, unwrap(result.data))
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
            res.step("Agent review", f"Evolus agent on {self.s.model_where}", 0, ok=False, note="unreachable: rule route used")
            return None
        # The agent may quote a full account number from the vendor library: mask every one before it is shown.
        verdict.explanation = mask_accounts(verdict.explanation)
        verdict.evidence = [mask_accounts(e) for e in verdict.evidence]
        verdict.supplier_question = mask_accounts(verdict.supplier_question)
        res.timings["agent_s"] = verdict.latency_s
        res.step("Agent review", f"Evolus agent on {self.s.model_where}", verdict.latency_s, ok=verdict.parsed,
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


def check_document(kind: str, name: str, blob: bytes) -> None:
    """Catch empty, wrong-type and cut-off files before spending an Evolus call on them."""
    doc = DOC_NAMES[kind]
    if not blob:
        raise _CaseError(f"The {doc} file is empty. Upload it again.")
    if blob.startswith(b"%PDF"):
        if b"%%EOF" not in blob[-2048:]:
            raise _CaseError(f"The {doc} PDF ({name}) is damaged or cut off. Ask the sender for a new copy; "
                             "a person must process this invoice.")
        return
    if blob.startswith((b"\x89PNG", b"\xff\xd8\xff")):
        return
    raise _CaseError(f"The {doc} file ({name}) isn't a PDF, PNG or JPG. Upload the document itself.")


def load_case_folder(folder: str | Path) -> dict[str, tuple[str, bytes]]:
    folder = Path(folder)
    return {k: (f"{k}.pdf", (folder / f"{k}.pdf").read_bytes()) for k in DOC_KINDS}
