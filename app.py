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

from ledgerpilot import recording  # noqa: E402
from ledgerpilot.agent_client import model_health, model_speed, model_usage  # noqa: E402
from ledgerpilot.audit import AuditLog  # noqa: E402
from ledgerpilot.config import TOKEN_FACTORY_SIGN_IN, ConfigError, load_settings  # noqa: E402
from ledgerpilot.fraud import mask  # noqa: E402
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
    "LOW_CONFIDENCE": "Agent review incomplete",
    "AGENT_CONCERN": "The agent raised a concern",
}
# Which check produced each finding code (shown beside the finding)
RULE = {
    **dict.fromkeys(["PRICE_VARIANCE", "PO_PRICE_AMBIGUOUS"], "Three-way match: unit price vs PO"),
    **dict.fromkeys(["QTY_NOT_RECEIVED"], "Three-way match: billed vs received"),
    **dict.fromkeys(["QTY_OVER_PO", "ITEM_NOT_ON_PO"], "Three-way match: billed vs ordered"),
    **dict.fromkeys(["LINE_ARITHMETIC", "SUBTOTAL_ARITHMETIC", "TOTAL_ARITHMETIC"], "Arithmetic check"),
    **dict.fromkeys(["TAX_OUT_OF_RANGE"], "Tax rate check"),
    **dict.fromkeys(["NEGATIVE_VALUE"], "Negative amount check"),
    **dict.fromkeys(["MISSING_FIELD"], "Completeness check"),
    **dict.fromkeys(["PO_MISMATCH", "GRN_PO_MISMATCH", "SUPPLIER_MISMATCH", "GRN_SUPPLIER_MISMATCH"],
                    "Document consistency"),
    **dict.fromkeys(["CURRENCY_MISMATCH"], "Currency check"),
    **dict.fromkeys(["PO_ALREADY_BILLED"], "PO balance check"),
    **dict.fromkeys(["BANK_MISMATCH", "BANK_MISSING"], "Fraud check: bank account vs vendor master"),
    **dict.fromkeys(["UNKNOWN_VENDOR"], "Fraud check: vendor master"),
    **dict.fromkeys(["DUPLICATE_INVOICE", "LOOKALIKE_INVOICE_NUMBER", "POSSIBLE_DUPLICATE"],
                    "Fraud check: duplicate invoices"),
    **dict.fromkeys(["LOW_CONFIDENCE", "AGENT_CONCERN"], "Human hand-off"),
}
CHECKS_RUN = ("three-way match (price, quantity received, quantity ordered)", "arithmetic", "tax rate",
              "currency", "PO balance", "vendor master", "bank account", "duplicate invoices")
# One click loads and checks the cases rehearsed for the demo
REHEARSAL = (("case_01", "Clean invoice"), ("case_07", "Overcharged by $200"), ("case_15", "Bank account changed"))

# Colours for LedgerPilot's own cards, matched to the Streamlit theme the viewer picked (⋮ › Settings)
THEME = "dark" if getattr(getattr(st.context, "theme", None), "type", None) == "dark" else "light"
PALETTE = {
    "light": {"card": "#FFFFFF", "ink": "#0F1B2D", "muted": "#5A6779", "rule": "#DCE3EC", "soft": "#EEF2F7",
              "ok": "#15803D", "hold": "#B45309", "fraud": "#B91C1C", "err": "#64748B", "accent": "#0F766E",
              "shadow": "0 1px 2px rgba(15,27,45,.06), 0 6px 18px rgba(15,27,45,.06)"},
    "dark": {"card": "#111A2B", "ink": "#E6ECF3", "muted": "#93A1B5", "rule": "#26344B", "soft": "#17233A",
             "ok": "#4ADE80", "hold": "#FBBF24", "fraud": "#F87171", "err": "#94A3B8", "accent": "#2DD4BF",
             "shadow": "0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.25)"},
}
CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo+Narrow:wght@700&display=swap');
.block-container { padding-top: 3.6rem; max-width: 1280px; }
.lp-num, .lp-kpi-value, .lp-figure, .lp-trail, .lp-amt { font-variant-numeric: tabular-nums; }

/* ---- header */
.lp-hero { position: relative; overflow: hidden; border-radius: 18px; padding: 1.45rem 1.7rem 1.3rem; color: #F1F5F9;
  background: radial-gradient(900px 260px at 100% 0%, rgba(45,212,191,.30), transparent 60%),
              radial-gradient(600px 220px at 0% 120%, rgba(59,130,246,.28), transparent 60%),
              linear-gradient(135deg, #0B1628 0%, #12305A 58%, #0F4C5C 100%);
  box-shadow: 0 12px 32px rgba(11,22,40,.22); }
.lp-hero::after { content: ""; position: absolute; inset: 0; pointer-events: none; opacity: .07;
  background-image: linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px);
  background-size: 28px 28px; mask-image: linear-gradient(90deg, transparent, #000 70%); }
.lp-brand { display: flex; align-items: center; gap: .85rem; position: relative; z-index: 1; }
.lp-logo { width: 46px; height: 46px; border-radius: 13px; flex: none; display: grid; place-items: center;
  background: linear-gradient(135deg, #2DD4BF, #3B82F6); box-shadow: 0 6px 16px rgba(45,212,191,.35); }
.lp-eyebrow { text-transform: uppercase; letter-spacing: .14em; font-size: .7rem; color: #99F6E4; font-weight: 600; margin: 0; }
.lp-title { font-size: 1.9rem; font-weight: 700; margin: 0; color: #FFFFFF; letter-spacing: -.02em; line-height: 1.15; }
.lp-lede { color: #CBD5E1; font-size: 1rem; margin: .7rem 0 0; max-width: 70ch; position: relative; z-index: 1; }
.lp-pills { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: 1rem; position: relative; z-index: 1; }
.lp-pill { display: inline-flex; align-items: center; gap: .45rem; padding: .3rem .75rem; border-radius: 999px;
  font-size: .8rem; font-weight: 500; color: #E2E8F0; background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.16); }
.lp-dot { width: 8px; height: 8px; border-radius: 50%; background: #94A3B8; flex: none; }
.lp-dot.on { background: #4ADE80; box-shadow: 0 0 0 0 rgba(74,222,128,.6); animation: lp-pulse 2.4s infinite; }
.lp-dot.warn { background: #FBBF24; } .lp-dot.off { background: #F87171; }
@keyframes lp-pulse { 0% { box-shadow: 0 0 0 0 rgba(74,222,128,.55); } 70% { box-shadow: 0 0 0 7px rgba(74,222,128,0); } 100% { box-shadow: 0 0 0 0 rgba(74,222,128,0); } }
.lp-model { color: #CBD5E1; font-size: .84rem; margin: .85rem 0 0; position: relative; z-index: 1; overflow-wrap: anywhere; }
.lp-model b { color: #FFFFFF; }

/* ---- metric cards */
.lp-kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: .75rem; margin: 1rem 0 .35rem; }
.lp-kpi { position: relative; overflow: hidden; background: var(--card); border: 1px solid var(--rule); border-radius: 14px;
  padding: .8rem 1rem .85rem 1.15rem; box-shadow: var(--shadow); transition: transform .15s ease, box-shadow .15s ease; }
.lp-kpi:hover { transform: translateY(-2px); }
.lp-kpi::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--k, var(--accent)); }
.lp-kpi-label { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .07em; font-weight: 600; }
.lp-kpi-value { display: block; font-size: 1.55rem; font-weight: 700; color: var(--ink); margin-top: .15rem; line-height: 1.2; }
.lp-kpi-sub { color: var(--muted); font-size: .78rem; }
@media (max-width: 1000px) { .lp-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

/* ---- section headings inside the main area */
.block-container h5 { font-size: .78rem !important; text-transform: uppercase; letter-spacing: .09em; color: var(--muted) !important;
  font-weight: 700 !important; margin-top: 1.1rem; padding-bottom: .1rem; }
.lp-small { color: var(--muted); font-size: .85rem; }
.lp-label { color: var(--muted); font-size: .8rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 600; margin: .4rem 0 .35rem; }

/* ---- decision card */
.lp-decision { --tone: var(--accent); position: relative; border-radius: 16px; border: 1px solid var(--rule); background: var(--card);
  border-left: 6px solid var(--tone); padding: 1.15rem 1.4rem 1.1rem; box-shadow: var(--shadow); margin-top: .4rem;
  background-image: linear-gradient(90deg, color-mix(in srgb, var(--tone) 10%, transparent), transparent 60%);
  display: grid; grid-template-columns: minmax(0, 2.2fr) minmax(0, 1fr); gap: 1rem 1.5rem; animation: lp-rise .3s ease-out 1; }
@keyframes lp-rise { from { transform: translateY(6px); opacity: 0; } to { transform: none; opacity: 1; } }
.lp-decision.ok { --tone: var(--ok); } .lp-decision.hold { --tone: var(--hold); }
.lp-decision.fraud { --tone: var(--fraud); } .lp-decision.err { --tone: var(--err); }
.lp-decision .lp-side { text-align: right; }
.lp-stamp { display: inline-block; font-family: 'Archivo Narrow', 'Arial Narrow', sans-serif; font-weight: 700;
  text-transform: uppercase; letter-spacing: .06em; font-size: 1.7rem; line-height: 1;
  padding: .45rem .8rem .4rem; border: 3px solid currentColor; border-radius: 6px; transform: rotate(-3deg);
  box-shadow: inset 0 0 0 2px var(--card), inset 0 0 0 4px currentColor; animation: lp-stamp .24s ease-out 1; }
@keyframes lp-stamp { from { transform: rotate(-3deg) scale(1.35); opacity: 0; } to { transform: rotate(-3deg) scale(1); opacity: 1; } }
.lp-ok { color: var(--ok); } .lp-hold { color: var(--hold); } .lp-fraud { color: var(--fraud); } .lp-err { color: var(--err); }
.lp-verdict { margin: .8rem 0 0; color: var(--ink); max-width: 62ch; overflow-wrap: anywhere; }
.lp-conf { margin: .45rem 0 0; font-size: .9rem; color: var(--muted); max-width: 62ch; }
.lp-conf-low { color: var(--hold); font-weight: 600; }
.lp-figure { font-size: 2rem; font-weight: 700; color: var(--tone); line-height: 1.1; }
.lp-figlabel { color: var(--muted); font-size: .8rem; text-transform: uppercase; letter-spacing: .07em; font-weight: 600; }
.lp-steps { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: .4rem; padding-top: .8rem; border-top: 1px dashed var(--rule); }
.lp-step { display: inline-flex; align-items: center; gap: .35rem; font-size: .76rem; padding: .22rem .62rem; border-radius: 999px;
  background: var(--soft); color: var(--ink); border: 1px solid var(--rule); }
.lp-step .ic { color: var(--ok); font-weight: 700; } .lp-step.bad .ic, .lp-step.bad { color: var(--fraud); }
.lp-step .s { color: var(--muted); }
.lp-doc { color: var(--muted); font-size: .95rem; margin: .9rem 0 .4rem; overflow-wrap: anywhere; }
.lp-doc b { color: var(--ink); }

/* ---- findings, agent note, trail */
.lp-finding { --tone: var(--hold); padding: .7rem .95rem; margin: .5rem 0; border: 1px solid var(--rule); border-left: 4px solid var(--tone);
  border-radius: 10px; background: var(--card); }
.lp-finding.fraud { --tone: var(--fraud); } .lp-finding.err { --tone: var(--err); } .lp-finding.ok { --tone: var(--ok); }
.lp-finding b { color: var(--ink); }
.lp-finding .lp-amt { float: right; font-weight: 700; color: var(--tone); }
.lp-finding p { margin: .2rem 0 0; color: var(--muted); font-size: .9rem; }
.lp-code { font-size: .74rem; color: var(--muted); background: var(--soft); border: 1px solid var(--rule); padding: .05rem .35rem; border-radius: 5px; }
.lp-rule { color: var(--muted); font-size: .82rem; margin-top: .15rem; }
.lp-clear { display: flex; gap: .7rem; align-items: flex-start; padding: .8rem 1rem; border-radius: 10px; border: 1px solid var(--rule);
  background: color-mix(in srgb, var(--ok) 8%, var(--card)); }
.lp-clear p { margin: 0; }
.lp-note { position: relative; border: 1px solid var(--rule); border-radius: 12px; background: var(--card); padding: .9rem 1rem .8rem 1rem;
  margin: .3rem 0 .6rem; box-shadow: var(--shadow); }
.lp-note .who { display: inline-flex; align-items: center; gap: .4rem; font-size: .72rem; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; color: var(--accent); margin-bottom: .4rem; }
.lp-note p { margin: 0 0 .4rem; color: var(--ink); }
.lp-note ul { margin: .2rem 0 0 1rem; color: var(--muted); font-size: .9rem; }
.lp-trail { width: 100%; border-collapse: collapse; font-size: .86rem; }
.lp-trail td { padding: .4rem .45rem; border-bottom: 1px solid var(--rule); vertical-align: top; }
.lp-trail td.t { text-align: right; white-space: nowrap; color: var(--muted); }
.lp-trail .okm { color: var(--ok); font-weight: 700; } .lp-trail .bad { color: var(--fraud); font-weight: 700; }
.lp-chip { display: inline-block; font-size: .76rem; font-weight: 700; padding: .12rem .55rem; border-radius: 999px;
  color: var(--tone); background: color-mix(in srgb, var(--tone) 14%, transparent); border: 1px solid color-mix(in srgb, var(--tone) 40%, transparent); }
.lp-chip.lp-ok { --tone: var(--ok); } .lp-chip.lp-hold { --tone: var(--hold); } .lp-chip.lp-fraud { --tone: var(--fraud); } .lp-chip.lp-err { --tone: var(--err); }
.lp-banner { border: 1.5px dashed var(--hold); color: var(--ink); border-radius: 12px; padding: .6rem .9rem; margin: .7rem 0;
  font-size: .9rem; overflow-wrap: anywhere; background: color-mix(in srgb, var(--hold) 8%, transparent); }
.lp-banner b { color: var(--hold); text-transform: uppercase; letter-spacing: .05em; }

/* ---- demo case buttons and the main action */
[class*="st-key-rehearse-"] button { min-height: 3.4rem; border-radius: 12px; border-left-width: 4px; font-weight: 600;
  transition: transform .12s ease, box-shadow .12s ease; }
[class*="st-key-rehearse-"] button:hover { transform: translateY(-2px); box-shadow: var(--shadow); }
.st-key-rehearse-case_01 button { border-left-color: var(--ok); }
.st-key-rehearse-case_07 button { border-left-color: var(--hold); }
.st-key-rehearse-case_15 button { border-left-color: var(--fraud); }
.st-key-check-btn button { min-height: 2.9rem; padding-left: 1.6rem; padding-right: 1.6rem; font-weight: 600;
  box-shadow: 0 6px 16px color-mix(in srgb, var(--accent) 35%, transparent); }

/* ---- review queue cards, tinted by decision */
[class*="st-key-q-"] { border-left: 5px solid var(--err) !important; border-radius: 14px !important; background: var(--card); box-shadow: var(--shadow); }
[class*="st-key-q-hold_for_review"] { border-left-color: var(--hold) !important; }
[class*="st-key-q-escalate_fraud"] { border-left-color: var(--fraud) !important; }
[class*="st-key-q-approve_for_payment"] { border-left-color: var(--ok) !important; }
.lp-qhead { font-size: 1rem; color: var(--ink); } .lp-qmeta { color: var(--muted); font-size: .86rem; margin-top: .15rem; }

/* ---- audit mix bar */
.lp-mix { display: flex; height: 12px; border-radius: 999px; overflow: hidden; background: var(--soft); margin: .4rem 0 .5rem; }
.lp-mix span { display: block; height: 100%; }
.lp-legend { display: flex; flex-wrap: wrap; gap: .9rem; font-size: .82rem; color: var(--muted); margin-bottom: .6rem; }
.lp-legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: .35rem; vertical-align: -1px; }

/* ---- empty states */
.lp-empty { text-align: center; padding: 2rem 1rem; border: 1.5px dashed var(--rule); border-radius: 14px; color: var(--muted); }
.lp-empty b { color: var(--ink); display: block; font-size: 1.02rem; margin-bottom: .25rem; }

/* ---- sidebar brand */
.lp-side-brand { display: flex; align-items: center; gap: .6rem; margin: -.4rem 0 .4rem; }
.lp-side-brand .lp-logo { width: 34px; height: 34px; border-radius: 10px; box-shadow: none; }
.lp-side-brand b { font-size: 1.05rem; } .lp-side-brand span { display: block; font-size: .74rem; opacity: .7; }

@media (prefers-reduced-motion: reduce) { .lp-stamp, .lp-decision, .lp-dot.on { animation: none; } .lp-kpi:hover { transform: none; } }
@media (max-width: 640px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; }
  .lp-hero { padding: 1.1rem 1.1rem 1rem; } .lp-title { font-size: 1.5rem; }
  .lp-decision { grid-template-columns: 1fr; } .lp-decision .lp-side { text-align: left; }
  .lp-stamp { font-size: 1.35rem; } .lp-finding .lp-amt { float: none; display: block; }
}
</style>"""
st.markdown("<style>:root { " + "; ".join(f"--{k}: {v}" for k, v in PALETTE[THEME].items()) + " }</style>" + CSS,
            unsafe_allow_html=True)

# The ledger-and-tick mark used in the header and sidebar
LOGO = ('<svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
        '<rect x="4" y="3" width="13" height="18" rx="2.2" stroke="#fff" stroke-width="1.8"/>'
        '<path d="M7.5 8h6M7.5 11.5h4" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>'
        '<circle cx="17" cy="17" r="4.6" fill="#0B1628" stroke="#fff" stroke-width="1.6"/>'
        '<path d="m15 17 1.4 1.4L19 15.8" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>')


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


@st.cache_data(ttl=120, show_spinner=False)
def cached_health(base_url: str, model: str) -> dict:
    # keyed on URL/model so a changed endpoint is re-checked; cached so a dead endpoint never slows every
    # click, and so the check doesn't eat into Token Factory's shared per-minute limit
    return model_health(settings, timeout=6)


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
model_problem = settings.model_problem()
health = cached_health(settings.amd_base_url, settings.amd_model) if not model_problem else None

with st.sidebar:
    st.markdown(f'<div class="lp-side-brand"><div class="lp-logo">{LOGO}</div>'
                '<div><b>LedgerPilot</b><span>Accounts-payable agent</span></div></div>', unsafe_allow_html=True)
    st.markdown("#### Connections")
    if model_problem:
        st.warning(f"AMD model endpoint isn't set up. {model_problem}")
    elif health["ok"]:
        st.success(f"AMD model online on {settings.model_where} ({health['latency_ms']} ms)  \n`{settings.amd_model}`")
        if st.button("Measure model speed", icon=":material/speed:", width="stretch",
                     help="Sends one short request straight to the AMD model endpoint and times it."):
            st.session_state["speed"] = model_speed(settings)
        speed = st.session_state.get("speed")
        if speed and speed["ok"]:
            st.caption(f"{speed['tokens_per_s']} tokens/s: {speed['tokens']} tokens in {speed['seconds']} s, "
                       "including time to first token.")
            if speed.get("limits"):
                st.caption("Rate limits left: " + ", ".join(f"{k.removeprefix('x-ratelimit-')} {v}"
                                                           for k, v in speed["limits"].items()))
        elif speed:
            st.caption(f"Speed test failed: {speed['detail']}")
        if settings.token_factory:
            if st.button("Check team usage", icon=":material/data_usage:", width="stretch",
                         help="Asks Token Factory how much of the daily quota your team's shared key has left."):
                st.session_state["usage"] = model_usage(settings)
            usage = st.session_state.get("usage")
            if usage and usage["ok"]:
                with st.expander("Token Factory usage (shared by your team)", icon=":material/insights:"):
                    st.json(usage["usage"])
            elif usage:
                st.caption(f"Usage check failed: {usage['detail']}")
    else:
        st.error(f"AMD model endpoint not reachable.  \n{health['detail']}")
    if settings.token_factory:
        st.caption(f"[AMD Token Factory]({TOKEN_FACTORY_SIGN_IN}): one free key per team, shared limits. "
                   "Send only the synthetic sample invoices.")
    missing = settings.missing()
    if missing:
        st.warning("Evolus isn't connected. Missing in .env: " + ", ".join(missing))
    else:
        st.success(f"Evolus workspace connected  \nAgent `{settings.evolus_agent_id}`")
        optional = [n for n, v in (("EVOLUS_WORKFLOW_ID", settings.workflow_id), ("EVOLUS_LIBRARY_ID", settings.library_id)) if not v]
        if optional:
            st.caption("Optional, not set: " + ", ".join(optional))
    st.caption("Checks run in Python. Reading, reasoning and actions run on Evolus, "
               + ("with the agent's model on AMD Token Factory." if settings.token_factory else
                  "with the agent's model served by vLLM on an AMD Instinct MI300X."))
    st.divider()
    st.markdown("#### Demo")
    recorded_cases = recording.available(settings.recordings_dir)
    # ?demo=1 opens the app in demo mode (a link to hand judges if the live services are down)
    demo_mode = st.toggle("Demo mode: replay recorded runs", key="demo_mode",
                          value=st.query_params.get("demo") == "1",
                          help="Shows saved outputs of earlier live runs, clearly labelled as recorded. "
                               "Use it if the live services are slow or down.")
    st.caption(f"{len(recorded_cases)} recorded case(s) available." if recorded_cases else
               "No recordings yet. `python eval/run_eval.py` saves one per case, or use "
               "'Save for demo mode' after a live check.")
    if st.button("Clear demo history", icon=":material/restart_alt:", width="stretch",
                 help="Empties the audit log so sample invoices can be checked again without being flagged as duplicates."):
        audit.reset()
        st.session_state.pop("result", None)
        st.session_state["toast"] = ("Demo history cleared. Sample invoices can be checked again.", ":material/restart_alt:")
        st.rerun()
    st.divider()
    st.caption(f"{'Dark' if THEME == 'dark' else 'Light'} theme. Switch in the ⋮ menu › Settings › Theme.")

# A toast queued by the previous run (a finished check, a review, a cleared history)
if toast := st.session_state.pop("toast", None):
    st.toast(toast[0], icon=toast[1])


# ------------------------------------------------------------------ header
rows_all = audit.all(limit=10_000)
checked = len(rows_all)
held_rows = [r for r in rows_all if r["final_route"] == "hold_for_review"]
held = sum(Decimal(r["money_at_risk"] or 0) for r in held_rows)
blocked = sum(1 for r in rows_all if r["final_route"] == "escalate_fraud")
ready = sum(1 for r in rows_all if r["final_route"] == "approve_for_payment")
pending_count = len(audit.pending_review())

if health and health["ok"]:
    speed = st.session_state.get("speed") or {}
    rate = f' · {speed["tokens_per_s"]} tokens/s' if speed.get("ok") else ""
    where = "AMD Token Factory" if settings.token_factory else "AMD Developer Cloud"
    model_line = (f'<b>Model:</b> {E(str(health["weights"]))} served on {where}'
                  f' · endpoint answered in {health["latency_ms"]} ms{rate}')
    model_pill = ("on", f"Model online · {E(settings.model_where)}")
elif health:
    model_line = f'<b>Model:</b> {E(settings.model_where)} endpoint not reachable'
    model_pill = ("off", "Model unreachable")
else:
    model_line = "<b>Model:</b> AMD model endpoint not set up (see the sidebar)"
    model_pill = ("warn", "Model not set up")
evolus_pill = ("warn", "Evolus not connected") if settings.missing() else ("on", "Evolus connected")
pills = [model_pill, evolus_pill, ("on", "Checks: Python, Decimal maths")]
if demo_mode:
    pills.append(("warn", "Demo mode: recorded runs"))
st.markdown(
    f'<div class="lp-hero"><div class="lp-brand"><div class="lp-logo">{LOGO}</div><div>'
    '<div class="lp-eyebrow">Accounts-payable agent · Evolus on AMD</div><div class="lp-title">LedgerPilot</div></div></div>'
    '<p class="lp-lede">Checks every supplier invoice against the purchase order and the delivery note, '
    'and stops wrong or fraudulent payments before they go out.</p>'
    '<div class="lp-pills">' + "".join(f'<span class="lp-pill"><span class="lp-dot {s}"></span>{t}</span>' for s, t in pills)
    + f'</div><p class="lp-model">{model_line}</p></div>', unsafe_allow_html=True)


def kpi(key: str, label: str, value: str, sub: str, tone: str) -> str:
    return (f'<div class="lp-kpi" style="--k: var(--{tone})"><span class="lp-kpi-label">{label}</span>'
            f'<span class="lp-kpi-value" data-kpi="{key}">{value}</span><span class="lp-kpi-sub">{sub}</span></div>')


st.markdown('<div class="lp-kpis">'
            + kpi("checked", "Invoices checked", str(checked), "since history was cleared", "accent")
            + kpi("ready", "Ready to pay", str(ready), "awaiting a person's yes", "ok")
            + kpi("held", "Held for review", money(held),
                  f"{len(held_rows)} invoice{'s' if len(held_rows) != 1 else ''} on hold", "hold")
            + kpi("blocked", "Payments blocked", str(blocked), "possible fraud", "fraud")
            + kpi("pending", "Awaiting review", str(pending_count), "in the review queue", "err")
            + "</div>", unsafe_allow_html=True)

intro, how = st.columns([4, 1.1], vertical_alignment="center")
if demo_mode:
    intro.markdown('<div class="lp-banner"><b>Demo mode</b> · Results below are replays of recorded live runs, '
                   'not live calls to Evolus or the AMD model. Turn it off in the sidebar to check invoices live.</div>',
                   unsafe_allow_html=True)
else:
    intro.markdown('<p class="lp-small">The model reads and explains; code does every number. '
                   'Nothing is paid until a person releases it from the review queue.</p>', unsafe_allow_html=True)
with how.popover("How it works", icon=":material/account_tree:", width="stretch"):
    st.markdown("**From three documents to a decision**")
    for n, (step, where_) in enumerate((
            ("Read the PO, delivery note and invoice", "Evolus document extractors"),
            ("Validate every field", "Python (Pydantic)"),
            ("Three-way match and fraud checks", "Python, Decimal maths"),
            ("Explain and route the case", f"Evolus agent on {settings.model_where}"),
            ("Draft the email, start the workflow", "Evolus AI Tool and workflow"),
            ("A person approves or rejects", "Review queue and audit log")), start=1):
        st.markdown(f"{n}. **{step}**  \n<span class='lp-small'>{E(where_)}</span>", unsafe_allow_html=True)
    st.caption("The agent can make a decision stricter than the checks, never looser.")

tab_check, tab_queue, tab_audit, tab_results = st.tabs(
    ["Check an invoice", f"Review queue ({pending_count})", "Audit log", "Results"])


# ------------------------------------------------------------------ result view
ROUTE_ICON = {"approve_for_payment": ":material/check_circle:", "hold_for_review": ":material/pause_circle:",
              "escalate_fraud": ":material/gpp_bad:", "processing_error": ":material/help:"}


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
    mark = ("background-color: rgba(248,113,113,0.18); color: #FCA5A5; font-weight: 600" if THEME == "dark" else
            "background-color: rgba(185,28,28,0.10); color: #991B1B; font-weight: 600")

    def per_row(r):
        out = {c: "" for c in r.index}
        billed, received, ordered = _num(r["Billed"]), _num(r["Received"]), _num(r["Ordered"])
        if _num(r["PO price"]) is None or _num(r["Billed price"]) != _num(r["PO price"]):
            out["Billed price"] = mark
        if billed is not None and ((received is None or billed > received) or (ordered is not None and billed > ordered)):
            out["Billed"] = mark
        return pd.Series(out)
    return df.style.apply(per_row, axis=1)


def _val(doc: dict, key: str | None) -> str:
    if key is None:
        return "–"  # this document doesn't carry the field
    value = doc.get(key)
    return "not read" if value in (None, "") else str(value)


def fields_table(res: CaseResult) -> pd.DataFrame:
    po, grn, inv = (res.extracted.get(k) or {} for k in ("po", "grn", "invoice"))
    rows = [("Number", "po_number", "grn_number", "invoice_number"),
            ("Date", "po_date", "received_date", "invoice_date"),
            ("PO it refers to", None, "po_number", "po_number"),
            ("Supplier ID", "supplier_id", "supplier_id", "supplier_id"),
            ("Supplier name", "supplier_name", None, "supplier_name"),
            ("Currency", "currency", None, "currency"),
            ("Subtotal", None, None, "subtotal"), ("Tax", None, None, "tax"), ("Total due", None, None, "total")]
    table = [{"Field": name, "Purchase order": _val(po, a), "Delivery note": _val(grn, b), "Invoice": _val(inv, c)}
             for name, a, b, c in rows]
    iban = inv.get("bank_iban")
    table.append({"Field": "Pay-to bank account", "Purchase order": "–", "Delivery note": "–",
                  "Invoice": mask(str(iban)) if iban else "not read"})
    return pd.DataFrame(table)


def finding_html(d) -> str:
    amount = f'<span class="lp-amt">{money(d.impact)}</span>' if d.impact is not None else ""
    label, tone, _ = STAMP.get(d.route.value, ("", "hold", ""))
    return (f'<div class="lp-finding {tone}">{amount}<b>{E(FINDING.get(d.code, d.code))}</b> '
            f'<code class="lp-code">{E(d.code)}</code>'
            f'<div class="lp-rule">Rule: {E(RULE.get(d.code, "Rules engine"))} → {E(label.lower())}</div>'
            f'<p>{E(d.message)}</p></div>')


def steps_html(res: CaseResult) -> str:
    """The pipeline at a glance: one pill per step, ticked or crossed, with its time."""
    pills = "".join(f'<span class="lp-step{"" if s["ok"] else " bad"}"><span class="ic">{"✓" if s["ok"] else "✗"}</span>'
                    f'{E(s["step"])} <span class="s">{s["seconds"]:.1f} s</span></span>' for s in res.steps)
    return f'<div class="lp-steps">{pills}</div>' if pills else ""


def show_result(res: CaseResult, recorded: dict | None = None) -> None:
    route = res.route.value
    label, cls, sentence = STAMP[route]
    if recorded:
        st.markdown(f'<div class="lp-banner"><b>Recorded run</b> · {E(str(recorded.get("case")))} recorded '
                    f'{E(str(recorded.get("at")))} with {E(str(recorded.get("model") or "unknown model"))} '
                    f'({E(str(recorded.get("source") or ""))}). This is a replay, not a live call.</div>',
                    unsafe_allow_html=True)
    conf = ""
    if not res.error:
        if res.confidence_reasons:
            conf = (f'<p class="lp-conf lp-conf-low">Low confidence, handed to a human reviewer: '
                    f'{E("; ".join(res.confidence_reasons))}.</p>')
        else:
            conf = ('<p class="lp-conf">High confidence: every value was read and the agent agrees with '
                    'the checks. A person still gives the final yes.</p>')
    st.markdown(
        f'<div class="lp-decision {cls}"><div>{stamp_html(route)}<p class="lp-verdict">{E(sentence)}</p>{conf}</div>'
        f'<div class="lp-side"><div class="lp-figure lp-num">{money(res.money_at_risk)}</div>'
        f'<div class="lp-figlabel">money at risk</div>'
        f'<div class="lp-small" style="margin-top:.5rem">{len(res.discrepancies)} finding(s), '
        f'decided in {res.timings.get("total_s", 0):.1f} s</div></div>{steps_html(res)}</div>', unsafe_allow_html=True)

    if res.error:
        st.error(res.error)
        if res.steps:
            st.markdown(trail_html(res), unsafe_allow_html=True)
        return

    inv = res.extracted.get("invoice") or {}
    st.markdown(f'<p class="lp-doc">Invoice <b>{E(str(inv.get("invoice_number")))}</b> from '
                f'<b>{E(str(inv.get("supplier_name") or inv.get("supplier_id")))}</b>, against PO {E(str(inv.get("po_number")))}, '
                f'total <b class="lp-num">{money(inv.get("total"))} {E(str(inv.get("currency") or ""))}</b></p>',
                unsafe_allow_html=True)

    left, right = st.columns([1.45, 1], gap="large")
    with left:
        st.markdown("##### Order, delivery and invoice side by side")
        df = match_table(res)
        if df.empty:
            st.info("No invoice lines could be read.")
        else:
            st.dataframe(style_match(df), hide_index=True, width="stretch")
            st.caption("Highlighted cells differ from the purchase order or the delivery note.")
        st.markdown("##### What the checks found")
        if res.discrepancies:
            st.markdown("".join(finding_html(d) for d in res.discrepancies), unsafe_allow_html=True)
            st.caption("Every figure here is calculated by code, not by the language model.")
        else:
            st.markdown('<div class="lp-clear"><span class="lp-ok" style="font-weight:700">✓</span><div>'
                        '<p>Nothing to flag. Quantities, prices, totals, supplier and bank account all check out.</p>'
                        f'<p class="lp-small">Checks that ran and passed: {E(", ".join(CHECKS_RUN))}.</p></div></div>',
                        unsafe_allow_html=True)
        with st.expander("Fields read from the documents", icon=":material/description:"):
            st.dataframe(fields_table(res), hide_index=True, width="stretch")
            st.caption("Read by the Evolus document extractors. The bank account is masked on screen.")
    with right:
        st.markdown("##### The agent's note")
        if res.agent:
            evidence = "".join(f"<li>{E(e)}</li>" for e in res.agent.evidence)
            st.markdown(f'<div class="lp-note"><div class="who">✦ LedgerPilot Clerk</div><p>{E(res.agent.explanation)}</p>'
                        f'{"<ul>" + evidence + "</ul>" if evidence else ""}</div>', unsafe_allow_html=True)
            if not res.agent.parsed:
                st.warning("The agent's reply couldn't be read as a decision, so the checks decided on their own.")
            elif res.agent.route and res.rule_route and res.agent.route.rank < res.rule_route.rank:
                st.warning(f"The agent suggested a softer decision ({STAMP[res.agent.route.value][0].lower()}). "
                           "The checks require the stricter one, so it was kept.")
            st.caption(f"{'Recorded: o' if recorded else 'O'}pen model on {settings.model_where} via Evolus, "
                       f"answered in {res.agent.latency_s:.1f} s")
        else:
            st.warning("The agent didn't answer, so the checks decided on their own. "
                       + E(res.trace.get("agent_error", "")))
        if res.email_draft:
            st.markdown("##### Draft email for a person to send" if route == "hold_for_review" else "##### Draft alert to the finance manager")
            st.text_area("Draft email", res.email_draft, height=210, label_visibility="collapsed")
            st.download_button("Download draft", res.email_draft, f"{inv.get('invoice_number') or 'invoice'}_draft.txt",
                               mime="text/plain", icon=":material/download:", key="dl-draft")
        st.markdown("##### What ran, where" + (" (when recorded)" if recorded else ""))
        st.markdown(trail_html(res), unsafe_allow_html=True)


def trail_html(res: CaseResult) -> str:
    rows = []
    for s in res.steps:
        mark = '<span class="okm">✓</span>' if s["ok"] else '<span class="bad">✗</span>'
        note = f'<div class="lp-small">{E(s["note"])}</div>' if s.get("note") else ""
        rows.append(f'<tr><td>{mark}</td><td>{E(s["step"])}{note}</td><td>{E(s["where"])}</td>'
                    f'<td class="t">{s["seconds"]:.2f} s</td></tr>')
    return f'<table class="lp-trail">{"".join(rows)}</table>' if rows else ""


# ------------------------------------------------------------------ check tab
def sample_options() -> dict[str, Path]:
    options = {}
    for f in sorted(SAMPLES.glob("case_*")):
        try:
            t = json.loads((f / "truth.json").read_text())
        except (OSError, ValueError, KeyError):
            continue  # a broken sample folder is skipped, not fatal
        options[f"{f.name.replace('_', ' ').capitalize()}: {t.get('description', '')}"] = f
    return options


def queue_case(option: str) -> None:
    """Rehearsal button: pick the sample and check it on the next run, in one click."""
    st.session_state["doc_mode"] = "Use a sample case"
    st.session_state["sample_pick"] = option
    st.session_state["run_now"] = True


def replay(case: str) -> bool:
    rec = recording.load(settings.recordings_dir, case)
    if rec is None:
        return False
    st.session_state.update(result=rec[0], result_meta=rec[1], result_case=case)
    return True


DEMO_ICON = {"case_01": ":material/check_circle:", "case_07": ":material/price_change:", "case_15": ":material/gpp_bad:"}
DEMO_HELP = {"case_01": "Everything matches: expect Ready to pay.",
             "case_07": "Unit price $2 above the PO on 100 chairs: expect On hold.",
             "case_15": "Correct amounts, but a new bank account: expect Payment blocked."}

with tab_check:
    options = sample_options()
    by_case = {f.name: name for name, f in options.items()}
    # ?case=case_07 checks that sample once when the page opens
    if not st.session_state.get("url_case_done") and st.query_params.get("case") in by_case:
        st.session_state["url_case_done"] = True
        queue_case(by_case[st.query_params["case"]])
    rehearsal = [(case, text) for case, text in REHEARSAL if case in by_case]
    if rehearsal:
        st.markdown('<p class="lp-label">Try a demo case: one click checks it</p>', unsafe_allow_html=True)
        for col, (case, text) in zip(st.columns(len(rehearsal)), rehearsal, strict=True):
            col.button(f"{text} ({case.replace('_', ' ')})", key=f"rehearse-{case}", on_click=queue_case,
                       args=(by_case[case],), width="stretch", icon=DEMO_ICON.get(case), help=DEMO_HELP.get(case))
    with st.container(border=True):
        mode = st.radio("Documents", ["Use a sample case", "Upload my own"], horizontal=True, key="doc_mode")
        docs, label = None, ""
        if mode == "Use a sample case":
            if not options:
                st.warning("No sample cases found. Run `python scripts/make_samples.py` first.")
            else:
                pick = st.selectbox("Sample case", list(options), key="sample_pick")
                folder = options[pick]
                c1, c2, c3 = st.columns(3)
                for col, (kind, name, icon) in zip((c1, c2, c3), (("po", "Purchase order", ":material/receipt_long:"),
                                                                  ("grn", "Delivery note", ":material/local_shipping:"),
                                                                  ("invoice", "Invoice", ":material/request_quote:")), strict=True):
                    col.download_button(f"View {name.lower()} (PDF)", (folder / f"{kind}.pdf").read_bytes(),
                                        f"{folder.name}_{kind}.pdf", mime="application/pdf", key=f"dl-{kind}",
                                        icon=icon, width="stretch")
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
                st.caption(f"{sum(bool(u) for u in (up_po, up_grn, up_inv))} of 3 documents added. "
                           "Add all three to check the invoice.")

        clicked = st.button("Replay recorded result" if demo_mode else "Check invoice", type="primary", key="check-btn",
                            icon=":material/replay:" if demo_mode else ":material/fact_check:", disabled=docs is None)
    if (clicked or st.session_state.pop("run_now", False)) and docs is not None:
        st.session_state.pop("notice", None)
        if demo_mode:
            if not replay(label):
                for k in ("result", "result_meta"):
                    st.session_state.pop(k, None)
                st.session_state["notice"] = (
                    f"No recording for {label} yet. Turn demo mode off to check it live, or record it first."
                    if mode == "Use a sample case" else
                    "Demo mode only replays recorded sample cases. Turn it off to check your own documents.")
            st.rerun()
        try:
            pipe = get_pipeline()
        except ConfigError as exc:
            st.error(f"Can't check invoices yet. {exc}")
            if recording.load(settings.recordings_dir, label):
                st.caption("A recorded run of this case exists: turn on demo mode in the sidebar to show it.")
            st.stop()
        except Exception as exc:  # noqa: BLE001 - never show a stack trace to a clerk or a judge
            st.error(f"LedgerPilot couldn't start ({type(exc).__name__}). Check the settings and data files.")
            st.stop()
        with st.status("Checking the invoice", expanded=True) as status:
            result = pipe.run(docs, label=label, progress=lambda m: status.write(m))
            status.update(label=STAMP[result.route.value][0], expanded=False,
                          state="error" if result.route is Route.ERROR else "complete")
        st.session_state.update(result=result, result_meta=None, result_case=label,
                                toast=(f"{label}: {STAMP[result.route.value][0]}", ROUTE_ICON[result.route.value]))
        st.rerun()

    if st.session_state.get("notice"):
        st.info(st.session_state["notice"])
    if "result" in st.session_state:
        res, meta, case = (st.session_state["result"], st.session_state.get("result_meta"),
                           st.session_state.get("result_case", ""))
        show_result(res, meta)
        if meta is None and res.route is Route.ERROR and recording.load(settings.recordings_dir, case):
            st.button("Show the recorded run of this case instead", key="fallback", icon=":material/history:",
                      help="Replays a saved live run, clearly labelled as recorded.", on_click=replay, args=(case,))
        if meta is None and res.route is not Route.ERROR and case in by_case:
            if st.button("Save for demo mode", key="save-rec", icon=":material/bookmark_add:",
                         help="Stores this live result so demo mode can replay it, labelled as recorded."):
                try:
                    recording.save(settings.recordings_dir, res, case,
                                   model=(health or {}).get("weights") or settings.amd_model, source="app, live check")
                    st.success(f"Saved. Demo mode will replay this run of {case}.")
                except OSError as exc:
                    st.error(f"Couldn't save the recording ({type(exc).__name__}). Check RECORDINGS_DIR is writable.")
    else:
        st.markdown('<div class="lp-empty"><b>No invoice checked yet</b>Pick a demo case above, or choose a sample '
                    'and press Check invoice. The decision, the evidence and the drafted email appear here.</div>',
                    unsafe_allow_html=True)


# ------------------------------------------------------------------ review queue
def review_case(case_id: int, decision: str, note_required: bool = False) -> None:
    """Button callback: runs before the page is redrawn, so the queue shows the new state straight away."""
    note = st.session_state.get(f"note{case_id}", "")
    if note_required and not note.strip():
        st.session_state["note_missing"] = case_id
        return
    audit.review(case_id, decision, note)
    st.session_state["toast"] = (("Released for payment." if decision == "approved_by_reviewer" else "Invoice rejected."),
                                 ":material/task_alt:" if decision == "approved_by_reviewer" else ":material/block:")


with tab_queue:
    pending = audit.pending_review()
    note_missing = st.session_state.pop("note_missing", None)
    if not pending:
        st.markdown('<div class="lp-empty"><b>Nothing waiting</b>Every checked invoice lands here, and nothing is paid '
                    'until a person releases it.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<p class="lp-small">{len(pending)} invoice{"s" if len(pending) != 1 else ""} waiting, newest first. '
                    'Release only what you have checked; a blocked payment needs a note saying how the supplier was '
                    'verified.</p>', unsafe_allow_html=True)
    for row in pending:
        with st.container(border=True, key=f"q-{row['final_route']}-{row['id']}"):
            info, act = st.columns([3, 1.15], gap="medium")
            info.markdown(f'<div class="lp-qhead">{chip(row["final_route"])}&nbsp; '
                          f'<b>{E(str(row["invoice_number"] or row["label"]))}</b> '
                          f'from {E(str(row["supplier_id"] or "unknown supplier"))}</div>'
                          f'<div class="lp-qmeta lp-num">Total {money(row["total"])} {E(str(row["currency"] or ""))} · '
                          f'at risk {money(row["money_at_risk"])} · checked {E(str(row["created_at"] or ""))[:16]}</div>',
                          unsafe_allow_html=True)
            if row["explanation"]:
                info.markdown(f'<div class="lp-small" style="margin-top:.4rem">{E(row["explanation"])}</div>',
                              unsafe_allow_html=True)
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
                act.button("Release for payment", key=f"ok{row['id']}", on_click=review_case, icon=":material/task_alt:",
                           args=(row["id"], "approved_by_reviewer", blocked_row), width="stretch")
                if note_missing == row["id"]:
                    act.error("Add a note saying how the supplier was verified.")
            act.button("Reject invoice", key=f"no{row['id']}", type="primary", on_click=review_case, icon=":material/block:",
                       args=(row["id"], "rejected_by_reviewer"), width="stretch")


# ------------------------------------------------------------------ audit log
MIX_TONE = {"Ready to pay": "ok", "On hold": "hold", "Payment blocked": "fraud", "Needs a person": "err"}

with tab_audit:
    rows = audit.all()
    if not rows:
        st.markdown('<div class="lp-empty"><b>No invoices checked yet</b>Every check is recorded here with its decision '
                    'and Evolus run IDs.</div>', unsafe_allow_html=True)
    else:
        df = pd.DataFrame(rows)
        df["Decision"] = df["final_route"].map(lambda r: STAMP.get(r, (r,))[0])
        counts = df["Decision"].value_counts()
        st.markdown('<p class="lp-label">Decision mix</p><div class="lp-mix">'
                    + "".join(f'<span style="width:{n / len(df) * 100:.2f}%;background:var(--{MIX_TONE.get(d, "err")})" '
                              f'title="{E(d)}: {n}"></span>' for d, n in counts.items())
                    + '</div><div class="lp-legend">'
                    + "".join(f'<span><i style="background:var(--{MIX_TONE.get(d, "err")})"></i>{E(d)} · {n}</span>'
                              for d, n in counts.items()) + "</div>", unsafe_allow_html=True)
        f1, f2 = st.columns([2, 1.3])
        choice = f1.multiselect("Show decisions", sorted(df["Decision"].unique()), default=sorted(df["Decision"].unique()))
        search = f2.text_input("Search invoice or supplier", placeholder="e.g. INV-1007 or V001")
        view = df[df["Decision"].isin(choice)]
        if search.strip():
            needle = search.strip().lower()
            view = view[view["invoice_number"].astype(str).str.lower().str.contains(needle, regex=False)
                        | view["supplier_id"].astype(str).str.lower().str.contains(needle, regex=False)]
        view = view[[
            "id", "created_at", "invoice_number", "supplier_id", "total", "currency", "Decision",
            "money_at_risk", "rule_route", "agent_route", "review_decision", "workflow_execution_id", "error"]].rename(columns={
            "id": "Case", "created_at": "Checked at (UTC)", "invoice_number": "Invoice", "supplier_id": "Supplier",
            "total": "Total", "currency": "Currency", "money_at_risk": "At risk", "rule_route": "Checks said",
            "agent_route": "Agent said", "review_decision": "Reviewer", "workflow_execution_id": "Workflow run", "error": "Error"})
        st.download_button("Download audit log (CSV)", view.to_csv(index=False), "ledgerpilot_audit.csv", mime="text/csv",
                           icon=":material/download:")
        st.dataframe(view, hide_index=True, width="stretch")


# ------------------------------------------------------------------ results
with tab_results:
    shown = False
    for name in ("evaluation.md", "benchmark.md"):
        path = ROOT / "docs" / name
        if path.exists():
            with st.container(border=True):
                st.markdown(path.read_text())
            shown = True
    if not shown:
        st.markdown('<div class="lp-empty"><b>No measured results yet</b>Run <code>python eval/run_eval.py</code> and '
                    '<code>python scripts/benchmark_amd.py</code> once the AMD endpoint and Evolus are connected; the '
                    'tables appear here.</div>', unsafe_allow_html=True)
