"""LedgerPilot AI - Streamlit front end.

    streamlit run app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ledgerpilot.agent_client import vllm_health  # noqa: E402
from ledgerpilot.audit import AuditLog  # noqa: E402
from ledgerpilot.config import ConfigError, load_settings  # noqa: E402
from ledgerpilot.pipeline import CaseResult, Pipeline, load_case_folder  # noqa: E402
from ledgerpilot.schemas import Route  # noqa: E402

st.set_page_config(page_title="LedgerPilot AI", page_icon="🧾", layout="wide")

ROUTE_STYLE = {
    "approve_for_payment": ("Approve for payment", "green", "No discrepancies. Ready for normal payment approval."),
    "hold_for_review": ("Hold for review", "orange", "Discrepancies found. Payment held; supplier query drafted."),
    "escalate_fraud": ("Escalated: possible fraud", "red", "Payment blocked. Finance manager alerted."),
    "processing_error": ("Processing error", "gray", "Could not be processed automatically. A person must handle it."),
}
SAMPLES = ROOT / "data" / "samples"

st.markdown("""
<style>
.block-container {padding-top: 1.6rem;}
.lp-badge {display:inline-block;padding:6px 14px;border-radius:999px;font-weight:600;color:white;}
.lp-kpi {font-size:0.8rem;color:#6b7280;margin-bottom:-6px;}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def get_settings():
    return load_settings()


settings = get_settings()
audit = AuditLog(settings.audit_db)


@st.cache_resource
def get_pipeline():
    return Pipeline(settings, audit)


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### 🧾 LedgerPilot AI")
    st.caption("Stops wrong and fraudulent supplier payments before they happen.")
    st.divider()
    st.markdown("**Infrastructure**")
    health = vllm_health(settings) if settings.vllm_base_url else {"ok": False, "detail": "VLLM_BASE_URL not set"}
    if health["ok"]:
        st.success(f"AMD MI300X · vLLM online ({health['latency_ms']} ms)\n\n`{', '.join(health['models'])}`")
    else:
        st.error(f"AMD vLLM endpoint: {health['detail']}")
    missing = settings.missing()
    if missing:
        st.error("Evolus not configured: " + ", ".join(missing))
    else:
        st.success(f"Evolus workspace `{settings.evolus_app_id}` · agent `{settings.evolus_agent_id}`")
    st.caption("Extractors · Agent · Vendor library · Email AI Tool · Routing workflow")
    st.divider()
    if st.button("Reset demo data", help="Clears the audit log so sample invoices are not flagged as duplicates."):
        audit.reset()
        st.session_state.pop("result", None)
        st.rerun()

tab_process, tab_queue, tab_audit, tab_results = st.tabs(["Process invoice", "Review queue", "Audit log", "Results"])


# ------------------------------------------------------------------ helpers
def badge(route: str) -> str:
    label, color, _ = ROUTE_STYLE[route]
    return f'<span class="lp-badge" style="background:{color}">{label}</span>'


def lines_table(res: CaseResult) -> pd.DataFrame:
    po = {l.get("sku"): l for l in (res.extracted.get("po") or {}).get("lines", [])}
    grn = {l.get("sku"): l for l in (res.extracted.get("grn") or {}).get("lines", [])}
    rows = []
    for l in (res.extracted.get("invoice") or {}).get("lines", []):
        sku = l.get("sku")
        rows.append({"SKU": sku, "Description": l.get("description"),
                     "PO qty": po.get(sku, {}).get("qty"), "Received": grn.get(sku, {}).get("qty_received"),
                     "Billed qty": l.get("qty"), "PO price": po.get(sku, {}).get("unit_price"),
                     "Billed price": l.get("unit_price"), "Line total": l.get("line_total")})
    return pd.DataFrame(rows)


def highlight(df: pd.DataFrame):
    def color_row(r):
        out = [""] * len(r)
        cols = list(r.index)

        def num(x):
            try:
                return float(str(x).replace(",", ""))
            except (TypeError, ValueError):
                return None
        red = "background-color: rgba(220,38,38,0.18); font-weight:600"
        if num(r["PO price"]) is None or (num(r["Billed price"]) != num(r["PO price"])):
            out[cols.index("Billed price")] = red
        if num(r["Received"]) is None or (num(r["Billed qty"]) or 0) > (num(r["Received"]) or 0):
            out[cols.index("Billed qty")] = red
        if num(r["PO qty"]) is not None and (num(r["Billed qty"]) or 0) > num(r["PO qty"]):
            out[cols.index("Billed qty")] = red
        return out
    return df.style.apply(color_row, axis=1)


def show_result(res: CaseResult) -> None:
    route = res.route.value
    _, _, sub = ROUTE_STYLE[route]
    c1, c2, c3, c4 = st.columns([2.2, 1, 1, 1])
    c1.markdown(badge(route), unsafe_allow_html=True)
    c1.caption(sub)
    c2.metric("Money at risk", f"{res.money_at_risk:,.2f}")
    c3.metric("Findings", len(res.discrepancies))
    c4.metric("Decision time", f"{res.timings.get('total_s', 0):.1f} s")

    if res.error:
        st.error(res.error)
        return

    inv = res.extracted.get("invoice", {})
    st.markdown(f"**Invoice {inv.get('invoice_number')}** · {inv.get('supplier_name')} ({inv.get('supplier_id')}) · "
                f"PO {inv.get('po_number')} · total {inv.get('total')} {inv.get('currency')}")

    left, right = st.columns([1.35, 1])
    with left:
        st.markdown("##### Three-way match")
        df = lines_table(res)
        if not df.empty:
            st.dataframe(highlight(df), hide_index=True, width="stretch")
        st.markdown("##### Findings (computed by code, not the model)")
        if res.discrepancies:
            st.dataframe(pd.DataFrame([d.as_row() for d in res.discrepancies])[["code", "message", "expected", "actual", "impact"]],
                         hide_index=True, width="stretch")
        else:
            st.success("PO, goods-received note and invoice agree. Supplier and bank details match the vendor master.")
    with right:
        st.markdown("##### Agent decision · open model on AMD MI300X")
        if res.agent:
            agent_route = res.agent.route.value if res.agent.route else "unparsed"
            st.write(res.agent.explanation)
            for e in res.agent.evidence:
                st.markdown(f"- {e}")
            if res.agent.route and res.rule_route and res.agent.route.rank < res.rule_route.rank:
                st.warning(f"Agent suggested **{agent_route}**, but the rules require **{res.rule_route.value}**. "
                           "The stricter route was kept.")
            st.caption(f"Agent route: {agent_route} · rule route: {res.rule_route.value if res.rule_route else '-'} · "
                       f"{res.agent.latency_s:.1f} s")
        else:
            st.warning("The agent did not answer; the rule-based route was used. " + res.trace.get("agent_error", ""))
        if res.email_draft:
            st.markdown("##### Draft email (Evolus AI Tool) · needs human approval")
            st.text_area("Draft", res.email_draft, height=200, label_visibility="collapsed")
        with st.expander("Trace: Evolus execution IDs and timings"):
            st.json({"workflow_execution_id": res.workflow_execution_id, "audit_case_id": res.audit_id,
                     "trace": res.trace, "timings_s": {k: round(v, 2) for k, v in res.timings.items()}})


# ------------------------------------------------------------------ process tab
with tab_process:
    st.subheader("Process a supplier invoice")
    mode = st.radio("Source", ["Sample case", "Upload my own PDFs"], horizontal=True, label_visibility="collapsed")
    docs, label = None, ""
    if mode == "Sample case":
        options = {}
        for f in sorted(SAMPLES.glob("case_*")):
            t = json.loads((f / "truth.json").read_text())
            options[f"{f.name} · {t['description']}"] = f
        pick = st.selectbox("Sample case", list(options))
        folder = options[pick]
        with st.expander("Documents in this case"):
            cols = st.columns(3)
            for col, kind in zip(cols, ("po", "grn", "invoice")):
                col.download_button(f"{kind.upper()}.pdf", (folder / f"{kind}.pdf").read_bytes(), f"{folder.name}_{kind}.pdf")
        docs, label = load_case_folder(folder), folder.name
    else:
        c1, c2, c3 = st.columns(3)
        up_po = c1.file_uploader("Purchase order", type=["pdf", "png", "jpg"])
        up_grn = c2.file_uploader("Goods-received note", type=["pdf", "png", "jpg"])
        up_inv = c3.file_uploader("Supplier invoice", type=["pdf", "png", "jpg"])
        if up_po and up_grn and up_inv:
            docs = {"po": (up_po.name, up_po.getvalue()), "grn": (up_grn.name, up_grn.getvalue()),
                    "invoice": (up_inv.name, up_inv.getvalue())}
            label = up_inv.name

    if st.button("Run LedgerPilot", type="primary", disabled=docs is None):
        try:
            pipe = get_pipeline()
        except ConfigError as exc:
            st.error(str(exc))
            st.stop()
        with st.status("Processing case...", expanded=True) as status:
            result = pipe.run(docs, label=label, progress=lambda m: status.write(m))
            status.update(label=ROUTE_STYLE[result.route.value][0], state="error" if result.route is Route.ERROR else "complete")
        st.session_state["result"] = result

    if "result" in st.session_state:
        st.divider()
        show_result(st.session_state["result"])

# ------------------------------------------------------------------ review queue
with tab_queue:
    st.subheader("Human review queue")
    pending = audit.pending_review()
    if not pending:
        st.info("Nothing waiting. Held and escalated invoices appear here for a person to decide.")
    for row in pending:
        with st.container(border=True):
            a, b = st.columns([3, 1])
            a.markdown(f"{badge(row['final_route'])} &nbsp; **{row['invoice_number'] or row['label']}** · "
                       f"{row['supplier_id'] or ''} · {row['total'] or ''} {row['currency'] or ''} · "
                       f"at risk {row['money_at_risk']}", unsafe_allow_html=True)
            if row["explanation"]:
                a.caption(row["explanation"])
            for d in json.loads(row["discrepancies"] or "[]"):
                a.markdown(f"- `{d['code']}` {d['message']}")
            note = b.text_input("Note", key=f"note{row['id']}", label_visibility="collapsed", placeholder="Reviewer note")
            if b.button("Approve anyway", key=f"ok{row['id']}"):
                audit.review(row["id"], "approved_by_reviewer", note); st.rerun()
            if b.button("Reject invoice", key=f"no{row['id']}", type="primary"):
                audit.review(row["id"], "rejected_by_reviewer", note); st.rerun()

# ------------------------------------------------------------------ audit log
with tab_audit:
    st.subheader("Audit log")
    rows = audit.all()
    if rows:
        df = pd.DataFrame(rows)[["id", "created_at", "label", "supplier_id", "invoice_number", "total", "currency",
                                 "rule_route", "agent_route", "final_route", "money_at_risk",
                                 "workflow_execution_id", "review_decision", "error"]]
        st.dataframe(df, hide_index=True, width="stretch")
        st.download_button("Download audit log (CSV)", df.to_csv(index=False), "ledgerpilot_audit.csv")
    else:
        st.info("No cases processed yet.")

# ------------------------------------------------------------------ results
with tab_results:
    st.subheader("Measured results")
    for name, title in (("evaluation.md", "Evaluation on 20 synthetic cases"), ("benchmark.md", "AMD MI300X cost and speed")):
        path = ROOT / "docs" / name
        if path.exists():
            st.markdown(path.read_text())
        else:
            st.info(f"{title}: not run yet. See README.")
