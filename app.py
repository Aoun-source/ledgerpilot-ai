"""LedgerPilot AI - Streamlit front end.

    streamlit run app.py
"""
from __future__ import annotations

import html
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ledgerpilot.agent_client import vllm_health, vllm_speed  # noqa: E402
from ledgerpilot.audit import AuditLog  # noqa: E402
from ledgerpilot.config import ConfigError, load_settings  # noqa: E402
from ledgerpilot.pipeline import CaseResult, Pipeline, load_case_folder  # noqa: E402
from ledgerpilot.schemas import Route  # noqa: E402

st.set_page_config(page_title="LedgerPilot AI", page_icon="🧾", layout="wide")

SAMPLES = ROOT / "data" / "samples"
E = html.escape  # everything from documents or the model is escaped before it touches HTML

STAMP = {
    "approve_for_payment": ("Ready to pay", "ok", "Purchase order, delivery and invoice agree. A person gives the final yes in the review queue."),
    "hold_for_review": ("On hold", "hold", "Payment is held until the supplier explains or corrects the invoice."),
    "escalate_fraud": ("Payment blocked", "fraud", "Possible fraud. Nothing is paid until a manager verifies the supplier by phone."),
    "processing_error": ("Needs a person", "err", "This invoice could not be checked automatically."),
}
FINDING = {
    "PRICE_VARIANCE": "Price above the agreed PO price",
    "QTY_NOT_RECEIVED": "Billed for goods not received",
    "QTY_OVER_PO": "Billed more than was ordered",
    "ITEM_NOT_ON_PO": "Item not on the purchase order",
    "LINE_ARITHMETIC": "Line total doesn't add up",
    "SUBTOTAL_ARITHMETIC": "Subtotal doesn't add up",
    "TOTAL_ARITHMETIC": "Total doesn't add up",
    "CURRENCY_MISMATCH": "Currency differs from the PO or vendor records",
    "NEGATIVE_VALUE": "Negative amount (possible credit note)",
    "PO_PRICE_AMBIGUOUS": "PO lists more than one price for the item",
    "LOOKALIKE_INVOICE_NUMBER": "Invoice number looks like one already processed",
    "TAX_OUT_OF_RANGE": "Tax looks too high",
    "PO_ALREADY_BILLED": "Purchase order already billed",
    "PO_MISMATCH": "Invoice cites a different PO",
    "GRN_PO_MISMATCH": "Delivery note is for a different PO",
    "SUPPLIER_MISMATCH": "Different supplier from the PO",
    "GRN_SUPPLIER_MISMATCH": "Delivery came from a different supplier",
    "MISSING_FIELD": "Information missing or unreadable",
    "BANK_MISMATCH": "Bank account differs from vendor records",
    "BANK_MISSING": "No bank account on the invoice",
    "UNKNOWN_VENDOR": "Supplier not in the vendor master",
    "DUPLICATE_INVOICE": "Invoice number already processed",
    "POSSIBLE_DUPLICATE": "Same amount billed recently",
}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&family=Archivo+Narrow:wght@700&display=swap');
:root { --paper:#F7F8F6; --ink:#1D2A36; --muted:#5B6670; --rule:#D5DCE3;
        --ok:#1F7A4D; --hold:#A86400; --fraud:#B3261E; --err:#5B6670; }
html, body, [class*="css"], .stMarkdown, .stDataFrame, button, input, textarea { font-family: 'Public Sans', system-ui, sans-serif; }
.block-container { padding-top: 4.5rem; max-width: 1240px; }
h1, h2, h3, h4 { font-family: 'Public Sans', system-ui, sans-serif; letter-spacing: -0.01em; color: var(--ink); }
.lp-title { font-size: 1.9rem; font-weight: 700; margin: 0; color: var(--ink); }
.lp-lede { color: var(--muted); font-size: 1.02rem; margin: .2rem 0 0; max-width: 62ch; }
.lp-model { color: var(--ink); font-size: .88rem; margin: .45rem 0 0; font-variant-numeric: tabular-nums; }
.lp-sofar { margin: .9rem 0 .2rem; padding: .55rem 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule);
            color: var(--ink); font-variant-numeric: tabular-nums; }
.lp-stamp { display: inline-block; font-family: 'Archivo Narrow', 'Arial Narrow', sans-serif; font-weight: 700;
            text-transform: uppercase; letter-spacing: .06em; font-size: 1.7rem; line-height: 1;
            padding: .45rem .8rem .4rem; border: 3px solid currentColor; border-radius: 6px;
            transform: rotate(-3deg); box-shadow: inset 0 0 0 2px var(--paper), inset 0 0 0 4px currentColor;
            animation: lp-stamp .22s ease-out 1; }
@keyframes lp-stamp { from { transform: rotate(-3deg) scale(1.35); opacity: 0; } to { transform: rotate(-3deg) scale(1); opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .lp-stamp { animation: none; } }
.lp-ok { color: var(--ok); } .lp-hold { color: var(--hold); } .lp-fraud { color: var(--fraud); } .lp-err { color: var(--err); }
.lp-verdict { margin: .7rem 0 0; color: var(--ink); max-width: 60ch; }
.lp-figure { font-variant-numeric: tabular-nums; font-size: 1.5rem; font-weight: 700; color: var(--ink); }
.lp-figlabel { color: var(--muted); font-size: .85rem; }
.lp-doc { color: var(--muted); font-size: .95rem; margin: .2rem 0 1rem; font-variant-numeric: tabular-nums; }
.lp-finding { padding: .55rem 0; border-bottom: 1px solid var(--rule); }
.lp-finding b { color: var(--ink); }
.lp-finding .lp-amt { float: right; font-variant-numeric: tabular-nums; font-weight: 600; }
.lp-finding p { margin: .15rem 0 0; color: var(--muted); font-size: .92rem; }
.lp-note { border-left: 3px solid var(--ink); padding: .2rem 0 .2rem .9rem; margin: .3rem 0 1rem; }
.lp-note p { margin: 0 0 .4rem; }
.lp-note ul { margin: .2rem 0 0 1rem; color: var(--muted); font-size: .92rem; }
.lp-small { color: var(--muted); font-size: .85rem; }
.lp-trail { width: 100%; border-collapse: collapse; font-size: .88rem; font-variant-numeric: tabular-nums; }
.lp-trail td { padding: .35rem .4rem; border-bottom: 1px solid var(--rule); vertical-align: top; }
.lp-trail td.t { text-align: right; white-space: nowrap; color: var(--muted); }
.lp-trail .bad { color: var(--fraud); font-weight: 600; }
.lp-chip { display: inline-block; font-size: .8rem; font-weight: 600; padding: .1rem .5rem; border-radius: 4px;
           border: 1.5px solid currentColor; }
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ setup
@st.cache_resource
def get_settings():
    return load_settings()


try:
    settings = get_settings()
except ConfigError as exc:
    st.error(f"Configuration problem: {exc}")
    st.stop()
audit = AuditLog(settings.audit_db)


@st.cache_resource
def get_pipeline():
    return Pipeline(settings, audit)


@st.cache_data(ttl=30, show_spinner=False)
def cached_health(base_url: str | None, model: str) -> dict:
    # keyed on URL/model so a changed endpoint is re-checked; cached so a dead endpoint never slows every click
    return vllm_health(settings, timeout=4)


def money(value) -> str:
    try:
        return f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError, TypeError):
        return "-"


def stamp_html(route: str) -> str:
    label, cls, _ = STAMP[route]
    return f'<span class="lp-stamp lp-{cls}" role="img" aria-label="Decision: {label}">{label}</span>'


def chip(route: str) -> str:
    label, cls, _ = STAMP.get(route, ("Unknown", "err", ""))
    return f'<span class="lp-chip lp-{cls}">{label}</span>'


# ------------------------------------------------------------------ sidebar
vllm_set = bool(settings.vllm_base_url) and not settings.placeholder_vllm()
health = cached_health(settings.vllm_base_url, settings.vllm_model) if vllm_set else None

with st.sidebar:
    st.markdown("#### Connections")
    if not vllm_set:
        st.warning("AMD model endpoint isn't set. Add VLLM_BASE_URL to .env.")
    elif health["ok"]:
        st.success(f"AMD MI300X model online ({health['latency_ms']} ms)  \n`{', '.join(health['models'])}`")
        if st.button("Measure model speed", help="Sends one short request straight to the vLLM endpoint and times it."):
            st.session_state["speed"] = vllm_speed(settings)
        speed = st.session_state.get("speed")
        if speed and speed["ok"]:
            st.caption(f"{speed['tokens_per_s']} tokens/s: {speed['tokens']} tokens in {speed['seconds']} s, "
                       "including time to first token.")
        elif speed:
            st.caption(f"Speed test failed: {speed['detail']}")
    else:
        st.error(f"AMD model endpoint not reachable.  \n{health['detail']}")
    missing = settings.missing()
    if missing:
        st.warning("Evolus isn't connected. Missing in .env: " + ", ".join(missing))
    else:
        st.success(f"Evolus workspace connected  \nAgent `{settings.evolus_agent_id}`")
        optional = [n for n, v in (("EVOLUS_WORKFLOW_ID", settings.workflow_id), ("EVOLUS_LIBRARY_ID", settings.library_id)) if not v]
        if optional:
            st.caption("Optional, not set: " + ", ".join(optional))
    st.caption("Checks run in Python. Reading, reasoning and actions run on Evolus, "
               "with the agent's model served by vLLM on an AMD Instinct MI300X.")
    st.divider()
    if st.button("Clear demo history", help="Empties the audit log so sample invoices can be checked again "
                                            "without being flagged as duplicates."):
        audit.reset()
        st.session_state.pop("result", None)
        st.rerun()


# ------------------------------------------------------------------ header
rows_all = audit.all(limit=10_000)
checked = len(rows_all)
held = sum(Decimal(r["money_at_risk"] or 0) for r in rows_all if r["final_route"] == "hold_for_review")
blocked = sum(1 for r in rows_all if r["final_route"] == "escalate_fraud")
st.markdown('<p class="lp-title">LedgerPilot</p>'
            '<p class="lp-lede">Checks every supplier invoice against the purchase order and the delivery note, '
            'and stops wrong or fraudulent payments before they go out.</p>', unsafe_allow_html=True)
if health and health["ok"]:
    speed = st.session_state.get("speed") or {}
    rate = f' · {speed["tokens_per_s"]} tokens/s' if speed.get("ok") else ""
    st.markdown(f'<p class="lp-model"><b>Model:</b> {E(str(health["weights"]))} served on AMD Developer Cloud'
                f' · endpoint answered in {health["latency_ms"]} ms{rate}</p>', unsafe_allow_html=True)
elif health:
    st.markdown('<p class="lp-model"><b>Model:</b> AMD Developer Cloud endpoint not reachable</p>',
                unsafe_allow_html=True)
else:
    st.markdown('<p class="lp-model"><b>Model:</b> not connected (set VLLM_BASE_URL)</p>', unsafe_allow_html=True)
if checked:
    st.markdown(f'<div class="lp-sofar">So far: {checked} invoice{"s" if checked != 1 else ""} checked, '
                f'{money(held)} held for review, {blocked} payment{"s" if blocked != 1 else ""} blocked as possible fraud.</div>',
                unsafe_allow_html=True)

pending_count = len(audit.pending_review())
tab_check, tab_queue, tab_audit, tab_results = st.tabs(
    ["Check an invoice", f"Review queue ({pending_count})", "Audit log", "Results"])


# ------------------------------------------------------------------ result view
def match_table(res: CaseResult) -> pd.DataFrame:
    po = {str(ln.get("sku")): ln for ln in (res.extracted.get("po") or {}).get("lines") or []}
    grn = {str(ln.get("sku")): ln for ln in (res.extracted.get("grn") or {}).get("lines") or []}
    rows = []
    for ln in (res.extracted.get("invoice") or {}).get("lines") or []:
        sku = str(ln.get("sku"))
        rows.append({"Item": sku, "Description": ln.get("description"),
                     "Ordered": po.get(sku, {}).get("qty"), "Received": grn.get(sku, {}).get("qty_received"),
                     "Billed": ln.get("qty"), "PO price": po.get(sku, {}).get("unit_price"),
                     "Billed price": ln.get("unit_price"), "Line total": ln.get("line_total")})
    return pd.DataFrame(rows).astype(object)


def _num(x):
    try:
        return Decimal(str(x).replace(",", ""))
    except (InvalidOperation, ValueError, TypeError):
        return None


def style_match(df: pd.DataFrame):
    mark = "background-color: rgba(179,38,30,0.12); color: #8C1D17; font-weight: 600"

    def per_row(r):
        out = {c: "" for c in r.index}
        billed, received, ordered = _num(r["Billed"]), _num(r["Received"]), _num(r["Ordered"])
        if _num(r["PO price"]) is None or _num(r["Billed price"]) != _num(r["PO price"]):
            out["Billed price"] = mark
        if billed is not None and ((received is None or billed > received) or (ordered is not None and billed > ordered)):
            out["Billed"] = mark
        return pd.Series(out)
    return df.style.apply(per_row, axis=1)


def show_result(res: CaseResult) -> None:
    route = res.route.value
    label, cls, sentence = STAMP[route]
    top_l, top_r = st.columns([2.2, 1])
    with top_l:
        st.markdown(stamp_html(route), unsafe_allow_html=True)
        st.markdown(f'<p class="lp-verdict">{E(sentence)}</p>', unsafe_allow_html=True)
    with top_r:
        st.markdown(f'<div class="lp-figure">{money(res.money_at_risk)}</div><div class="lp-figlabel">money at risk</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="lp-small" style="margin-top:.5rem">{len(res.discrepancies)} finding(s), '
                    f'decided in {res.timings.get("total_s", 0):.1f} s</div>', unsafe_allow_html=True)

    if res.error:
        st.error(res.error)
        if res.steps:
            st.markdown(trail_html(res), unsafe_allow_html=True)
        return

    inv = res.extracted.get("invoice") or {}
    st.markdown(f'<p class="lp-doc">Invoice <b>{E(str(inv.get("invoice_number")))}</b> from '
                f'{E(str(inv.get("supplier_name") or inv.get("supplier_id")))}, against PO {E(str(inv.get("po_number")))}, '
                f'total {money(inv.get("total"))} {E(str(inv.get("currency") or ""))}</p>', unsafe_allow_html=True)

    left, right = st.columns([1.45, 1], gap="large")
    with left:
        st.markdown("##### Order, delivery and invoice side by side")
        df = match_table(res)
        if df.empty:
            st.info("No invoice lines could be read.")
        else:
            st.dataframe(style_match(df), hide_index=True, width="stretch")
        st.markdown("##### What the checks found")
        if res.discrepancies:
            parts = []
            for d in res.discrepancies:
                amount = f'<span class="lp-amt">{money(d.impact)}</span>' if d.impact is not None else ""
                parts.append(f'<div class="lp-finding">{amount}<b>{E(FINDING.get(d.code, d.code))}</b>'
                             f'<p>{E(d.message)}</p></div>')
            st.markdown("".join(parts), unsafe_allow_html=True)
            st.caption("Every figure here is calculated by code, not by the language model.")
        else:
            st.markdown('<p>Nothing to flag. Quantities, prices, totals, supplier and bank account all check out.</p>',
                        unsafe_allow_html=True)
    with right:
        st.markdown("##### The agent's note")
        if res.agent:
            evidence = "".join(f"<li>{E(e)}</li>" for e in res.agent.evidence)
            st.markdown(f'<div class="lp-note"><p>{E(res.agent.explanation)}</p>'
                        f'{"<ul>" + evidence + "</ul>" if evidence else ""}</div>', unsafe_allow_html=True)
            if not res.agent.parsed:
                st.warning("The agent's reply couldn't be read as a decision, so the checks decided on their own.")
            elif res.agent.route and res.rule_route and res.agent.route.rank < res.rule_route.rank:
                st.warning(f"The agent suggested a softer decision ({STAMP[res.agent.route.value][0].lower()}). "
                           "The checks require the stricter one, so it was kept.")
            st.caption(f"Open model on AMD MI300X via Evolus, answered in {res.agent.latency_s:.1f} s")
        else:
            st.warning("The agent didn't answer, so the checks decided on their own. "
                       + E(res.trace.get("agent_error", "")))
        if res.email_draft:
            st.markdown("##### Draft email for a person to send" if route == "hold_for_review" else "##### Draft alert to the finance manager")
            st.text_area("Draft email", res.email_draft, height=210, label_visibility="collapsed")
        st.markdown("##### What ran, where")
        st.markdown(trail_html(res), unsafe_allow_html=True)


def trail_html(res: CaseResult) -> str:
    rows = []
    for s in res.steps:
        mark = "✓" if s["ok"] else '<span class="bad">✗</span>'
        note = f'<div class="lp-small">{E(s["note"])}</div>' if s.get("note") else ""
        rows.append(f'<tr><td>{mark}</td><td>{E(s["step"])}{note}</td><td>{E(s["where"])}</td>'
                    f'<td class="t">{s["seconds"]:.2f} s</td></tr>')
    return f'<table class="lp-trail">{"".join(rows)}</table>' if rows else ""


# ------------------------------------------------------------------ check tab
with tab_check:
    mode = st.radio("Documents", ["Use a sample case", "Upload my own"], horizontal=True)
    docs, label = None, ""
    if mode == "Use a sample case":
        options = {}
        for f in sorted(SAMPLES.glob("case_*")):
            t = json.loads((f / "truth.json").read_text())
            options[f"{f.name.replace('_', ' ').capitalize()}: {t['description']}"] = f
        if not options:
            st.warning("No sample cases found. Run `python scripts/make_samples.py` first.")
        else:
            pick = st.selectbox("Sample case", list(options))
            folder = options[pick]
            c1, c2, c3 = st.columns(3)
            for col, (kind, name) in zip((c1, c2, c3), (("po", "Purchase order"), ("grn", "Delivery note"),
                                                        ("invoice", "Invoice")), strict=True):
                col.download_button(f"View {name.lower()} (PDF)", (folder / f"{kind}.pdf").read_bytes(),
                                    f"{folder.name}_{kind}.pdf", mime="application/pdf", key=f"dl-{kind}")
            docs, label = load_case_folder(folder), folder.name
    else:
        c1, c2, c3 = st.columns(3)
        up_po = c1.file_uploader("Purchase order", type=["pdf", "png", "jpg", "jpeg"])
        up_grn = c2.file_uploader("Delivery note (goods received)", type=["pdf", "png", "jpg", "jpeg"])
        up_inv = c3.file_uploader("Supplier invoice", type=["pdf", "png", "jpg", "jpeg"])
        if up_po and up_grn and up_inv:
            docs = {"po": (up_po.name, up_po.getvalue()), "grn": (up_grn.name, up_grn.getvalue()),
                    "invoice": (up_inv.name, up_inv.getvalue())}
            label = up_inv.name
        else:
            st.caption("Add all three documents to check the invoice.")

    if st.button("Check invoice", type="primary", disabled=docs is None):
        try:
            pipe = get_pipeline()
        except ConfigError as exc:
            st.error(f"Can't check invoices yet. {exc}")
            st.stop()
        with st.status("Checking the invoice", expanded=True) as status:
            result = pipe.run(docs, label=label, progress=lambda m: status.write(m))
            status.update(label=STAMP[result.route.value][0], expanded=False,
                          state="error" if result.route is Route.ERROR else "complete")
        st.session_state["result"] = result
        st.rerun()

    if "result" in st.session_state:
        st.divider()
        show_result(st.session_state["result"])


# ------------------------------------------------------------------ review queue
def review_case(case_id: int, decision: str, note_required: bool = False) -> None:
    """Button callback: runs before the page is redrawn, so the queue shows the new state straight away."""
    note = st.session_state.get(f"note{case_id}", "")
    if note_required and not note.strip():
        st.session_state["note_missing"] = case_id
        return
    audit.review(case_id, decision, note)


with tab_queue:
    pending = audit.pending_review()
    note_missing = st.session_state.pop("note_missing", None)
    if not pending:
        st.info("Nothing waiting. Every checked invoice lands here, and nothing is paid until a person releases it.")
    for row in pending:
        with st.container(border=True):
            info, act = st.columns([3, 1.1])
            info.markdown(f'{chip(row["final_route"])}&nbsp; <b>{E(str(row["invoice_number"] or row["label"]))}</b> '
                          f'from {E(str(row["supplier_id"] or "unknown supplier"))}, '
                          f'{money(row["total"])} {E(str(row["currency"] or ""))}, '
                          f'at risk {money(row["money_at_risk"])}', unsafe_allow_html=True)
            if row["explanation"]:
                info.markdown(f'<div class="lp-small">{E(row["explanation"])}</div>', unsafe_allow_html=True)
            if row["error"]:
                info.markdown(f'<div class="lp-small">{E(row["error"])}</div>', unsafe_allow_html=True)
            for d in json.loads(row["discrepancies"] or "[]"):
                info.markdown(f'<div class="lp-small">• {E(FINDING.get(d["code"], d["code"]))}: {E(d["message"])}</div>',
                              unsafe_allow_html=True)
            blocked_row = row["final_route"] == "escalate_fraud"
            act.text_input("Reviewer note", key=f"note{row['id']}",
                           placeholder="Required to release a blocked payment" if blocked_row else "Optional note")
            if row["final_route"] == "processing_error":
                # An invoice that could not be read can never be released from here.
                act.caption("Can't be paid from here. Check the documents by hand or upload readable copies.")
            else:
                act.button("Release for payment", key=f"ok{row['id']}", on_click=review_case,
                           args=(row["id"], "approved_by_reviewer", blocked_row))
                if note_missing == row["id"]:
                    act.error("Add a note saying how the supplier was verified.")
            act.button("Reject invoice", key=f"no{row['id']}", type="primary", on_click=review_case,
                       args=(row["id"], "rejected_by_reviewer"))


# ------------------------------------------------------------------ audit log
with tab_audit:
    rows = audit.all()
    if not rows:
        st.info("No invoices checked yet. Every check is recorded here with its decision and Evolus run IDs.")
    else:
        df = pd.DataFrame(rows)
        df["Decision"] = df["final_route"].map(lambda r: STAMP.get(r, (r,))[0])
        choice = st.multiselect("Show decisions", sorted(df["Decision"].unique()), default=sorted(df["Decision"].unique()))
        view = df[df["Decision"].isin(choice)][[
            "id", "created_at", "invoice_number", "supplier_id", "total", "currency", "Decision",
            "money_at_risk", "rule_route", "agent_route", "review_decision", "workflow_execution_id", "error"]].rename(columns={
            "id": "Case", "created_at": "Checked at (UTC)", "invoice_number": "Invoice", "supplier_id": "Supplier",
            "total": "Total", "currency": "Currency", "money_at_risk": "At risk", "rule_route": "Checks said",
            "agent_route": "Agent said", "review_decision": "Reviewer", "workflow_execution_id": "Workflow run", "error": "Error"})
        st.dataframe(view, hide_index=True, width="stretch")
        st.download_button("Download audit log (CSV)", view.to_csv(index=False), "ledgerpilot_audit.csv", mime="text/csv")


# ------------------------------------------------------------------ results
with tab_results:
    shown = False
    for name in ("evaluation.md", "benchmark.md"):
        path = ROOT / "docs" / name
        if path.exists():
            st.markdown(path.read_text())
            shown = True
    if not shown:
        st.info("No measured results yet. Run `python eval/run_eval.py` and `python scripts/benchmark_amd.py` "
                "once the AMD endpoint and Evolus are connected; the tables appear here.")
