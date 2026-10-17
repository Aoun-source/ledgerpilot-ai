"""LedgerPilot AI - Streamlit front end.

    streamlit run app.py
"""
from __future__ import annotations

import html
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import altair as alt
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

st.set_page_config(page_title="LedgerPilot", page_icon=":material/receipt_long:", layout="wide")

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

# Colours for LedgerPilot's own elements. The app ships a dark theme; the light set is only used if a viewer
# switches Streamlit to its light theme from the ⋮ menu.
THEME = "light" if getattr(getattr(st.context, "theme", None), "type", None) == "light" else "dark"
PALETTE = {
    "dark": {"bg": "#0E0F10", "surface": "#131416", "raised": "#18191C", "line": "#232528", "line-2": "#2E3034",
             "ink": "#EDE9E3", "ink-2": "#BDB8B0", "muted": "#8A867F", "faint": "#5F5C57",
             "accent": "#34B27D", "accent-2": "#3FC48C", "accent-ink": "#6FD3A6", "accent-soft": "rgba(52,178,125,.12)",
             "ok": "#4FBF8B", "hold": "#D9A24A", "fraud": "#E2674F", "err": "#8A867F",
             "shadow": "0 1px 0 rgba(255,255,255,.03) inset, 0 12px 32px -12px rgba(0,0,0,.55)"},
    "light": {"bg": "#FBFAF8", "surface": "#FFFFFF", "raised": "#F4F2EE", "line": "#E7E4DE", "line-2": "#D9D5CE",
              "ink": "#1C1B19", "ink-2": "#45423D", "muted": "#6F6B64", "faint": "#9A958D",
              "accent": "#1F8A5B", "accent-2": "#23996A", "accent-ink": "#1F8A5B", "accent-soft": "rgba(31,138,91,.10)",
              "ok": "#1F8A5B", "hold": "#9A6A12", "fraud": "#B8432D", "err": "#6F6B64",
              "shadow": "0 1px 2px rgba(28,27,25,.05), 0 12px 32px -16px rgba(28,27,25,.18)"},
}
CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&display=swap');

/* ---------- canvas */
.block-container { padding-top: 3.4rem; padding-bottom: 5rem; max-width: 1180px; }
::selection { background: var(--accent-soft); }
.lp-serif { font-family: 'Instrument Serif', Georgia, serif; font-weight: 400; letter-spacing: -.005em; }
.lp-mono, .lp-num { font-family: 'Geist Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.lp-eyebrow { display: flex; align-items: center; gap: .6rem; color: var(--muted); font-size: .8rem; font-weight: 500; margin: 0 0 .55rem; }
.lp-eyebrow::before { content: ""; width: 18px; height: 1px; background: var(--accent); }
.lp-h { color: var(--ink); font-size: .95rem; font-weight: 600; margin: 0 0 .2rem; }
.lp-sub { color: var(--muted); font-size: .86rem; margin: 0 0 .9rem; line-height: 1.5; }
.lp-small { color: var(--muted); font-size: .84rem; }
.block-container h5 { font-size: .8rem !important; font-weight: 500 !important; color: var(--muted) !important;
  margin: 2rem 0 .6rem; letter-spacing: .01em; padding: 0; }

/* Streamlit sizes every markdown paragraph; these classes need to win */
[data-testid="stMarkdownContainer"] p.lp-sub { font-size: .86rem; margin: 0 0 .9rem; }
[data-testid="stMarkdownContainer"] p.lp-scn { font-size: .78rem; margin: -.4rem 0 .85rem .1rem; }
[data-testid="stMarkdownContainer"] p.lp-srcs { font-size: .8rem; margin: 0; }
[data-testid="stMarkdownContainer"] p.lp-side-foot { font-size: .76rem; margin-top: 2rem; }
[data-testid="stMarkdownContainer"] p.lp-verdict { font-size: 1.02rem; margin: .7rem 0 0; }
[data-testid="stMarkdownContainer"] p.lp-conf { font-size: .86rem; margin: .4rem 0 0; }
[data-testid="stMarkdownContainer"] .lp-quote p { font-size: 1.32rem; }
[data-testid="stMarkdownContainer"] .lp-finding p { font-size: .86rem; margin: .3rem 0 0; }
[data-testid="stMarkdownContainer"] .lp-clear p { font-size: .92rem; }
[data-testid="stMarkdownContainer"] .lp-clear p.lp-small { font-size: .84rem; margin-top: .3rem; }

/* ---------- header: a quiet display line on the left, connection status on the right */
.lp-display { font-family: 'Instrument Serif', Georgia, serif; font-weight: 400; color: var(--ink);
  font-size: clamp(2rem, 3.4vw, 2.75rem); line-height: 1.04; letter-spacing: -.012em; margin: 0; }
.lp-display em { font-style: italic; color: var(--muted); }
.lp-conn { border-left: 1px solid var(--line); padding: .1rem 0 .1rem 1.1rem; }
.lp-conn .row { display: grid; grid-template-columns: 10px 1fr; gap: .55rem; align-items: baseline;
  font-size: .82rem; color: var(--muted); line-height: 1.45; padding: .18rem 0; overflow-wrap: anywhere; }
.lp-conn b { color: var(--ink-2); font-weight: 500; }
.lp-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--faint); display: inline-block; transform: translateY(-1px); }
.lp-dot.on { background: var(--ok); box-shadow: 0 0 0 3px rgba(79,191,139,.12); }
.lp-dot.warn { background: var(--hold); } .lp-dot.off { background: var(--fraud); }

/* ---------- the ledger: summary figures between two rules */
.lp-ledger { display: grid; grid-template-columns: 1.15fr 1fr 1.3fr 1fr 1fr; margin: 2.2rem 0 0;
  border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.lp-fig { padding: 1.05rem 1.2rem 1.1rem; border-left: 1px solid var(--line); min-width: 0; }
.lp-fig:first-child { border-left: 0; padding-left: 0; }
.lp-fig .k { color: var(--muted); font-size: .8rem; }
.lp-fig .v { color: var(--ink); font-size: 1.85rem; font-weight: 500; letter-spacing: -.025em; line-height: 1.2;
  margin-top: .3rem; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lp-fig .v small { font-size: .9rem; color: var(--muted); font-weight: 400; margin-left: .25rem; letter-spacing: 0; }
.lp-fig .s { color: var(--faint); font-size: .76rem; margin-top: .15rem; }
.lp-mixrow { display: flex; align-items: center; gap: 1.2rem; margin: .7rem 0 2rem; }
.lp-mix { flex: 1; display: flex; height: 3px; border-radius: 2px; overflow: hidden; background: var(--line); gap: 2px; }
.lp-mix span { display: block; height: 100%; transition: width .5s ease; }
.lp-legend { display: flex; flex-wrap: wrap; gap: .2rem 1rem; font-size: .76rem; color: var(--muted); white-space: nowrap; }
.lp-legend i { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: .4rem; transform: translateY(-1px); }
.lp-legend.empty { color: var(--faint); }

/* ---------- navigation tabs */
[data-testid="stTabs"] [role="tablist"] { gap: 1.75rem; border-bottom: 1px solid var(--line); }
[data-testid="stTab"] { padding: .55rem 0 .7rem; }
[data-testid="stTab"] p { font-size: .9rem; font-weight: 500; color: var(--muted); transition: color .15s ease; }
[data-testid="stTab"]:hover p, [data-testid="stTab"][aria-selected="true"] p { color: var(--ink); }
[data-testid="stTabs"] .react-aria-SelectionIndicator { background: var(--accent) !important; height: 1.5px !important; }
[data-testid="stTabPanel"] { padding-top: 1.6rem; }

/* ---------- buttons and inputs */
[data-testid="stBaseButton-secondary"], [data-testid="stPopoverButton"] { background: transparent; border-color: var(--line-2);
  color: var(--ink); font-weight: 500; transition: background-color .15s ease, border-color .15s ease, color .15s ease; }
[data-testid="stBaseButton-secondary"]:hover, [data-testid="stPopoverButton"]:hover { background: var(--raised);
  border-color: var(--faint); color: var(--ink); }
[data-testid="stBaseButton-primary"] { background: var(--accent); border-color: var(--accent); color: #05140D; font-weight: 600;
  box-shadow: 0 1px 0 rgba(255,255,255,.18) inset, 0 6px 16px -8px rgba(52,178,125,.6); transition: background-color .15s ease, transform .15s ease; }
[data-testid="stBaseButton-primary"]:hover { background: var(--accent-2); border-color: var(--accent-2); color: #05140D; }
[data-testid="stBaseButton-primary"]:active { transform: translateY(1px); }
[data-testid="stBaseButton-primary"]:disabled { background: var(--raised); border-color: var(--line); color: var(--faint); box-shadow: none; }
[data-testid="stBaseButton-tertiary"] { color: var(--accent-ink); font-weight: 500; padding-left: 0; padding-right: 0; }
[data-testid="stBaseButton-tertiary"]:hover { color: var(--ink); }
button:focus-visible { outline: 2px solid var(--accent) !important; outline-offset: 2px; }
[data-testid="stWidgetLabel"] p { color: var(--muted); font-size: .82rem; font-weight: 500; }
[data-baseweb="tag"] { background: var(--raised) !important; border: 1px solid var(--line-2); }
[data-baseweb="tag"] span { color: var(--ink-2) !important; }

/* main-area notices: a quiet panel, not a coloured slab */
[data-testid="stMain"] [data-testid="stAlertContainer"] { background: var(--surface) !important; border: 1px solid var(--line); }
[data-testid="stExpander"] details { border-color: var(--line); background: transparent; border-radius: 8px; }
[data-testid="stExpander"] summary p { font-size: .88rem; color: var(--ink-2); }
[data-testid="stToast"] { background: var(--raised); border: 1px solid var(--line-2); box-shadow: var(--shadow); }

/* ---------- scenarios and the documents panel */
[class*="st-key-scn-"] button { justify-content: flex-start; text-align: left; min-height: 0; padding: .7rem .9rem;
  border-color: var(--line); background: var(--surface); }
[class*="st-key-scn-"] button > div { width: 100%; justify-content: flex-start; }
[class*="st-key-scn-"] button p { font-weight: 500; text-align: left; }
[class*="st-key-scn-"] button:hover { border-color: var(--line-2); background: var(--raised); }
.lp-scn { color: var(--faint); font-size: .78rem; margin: -.35rem 0 .8rem .1rem; line-height: 1.45; }
.st-key-docs-panel { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 1.2rem 1.3rem 1.3rem;
  box-shadow: var(--shadow); }
.lp-srcs { color: var(--muted); font-size: .8rem; margin: .2rem 0 0; }

/* ---------- decision */
.lp-verdict-block { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, auto); gap: 1.4rem 3rem;
  margin-top: 2.6rem; padding-top: 2rem; border-top: 1px solid var(--line); animation: lp-in .35s ease-out 1; }
@keyframes lp-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
.lp-stamp { font-family: 'Instrument Serif', Georgia, serif; font-weight: 400; font-size: clamp(2.3rem, 4vw, 3rem);
  line-height: 1; letter-spacing: -.01em; display: inline-block; }
.lp-ok { color: var(--ok); } .lp-hold { color: var(--hold); } .lp-fraud { color: var(--fraud); } .lp-err { color: var(--ink-2); }
.lp-verdict { color: var(--ink); font-size: 1.02rem; margin: .7rem 0 0; max-width: 56ch; line-height: 1.55; overflow-wrap: anywhere; }
.lp-conf { color: var(--muted); font-size: .86rem; margin: .4rem 0 0; max-width: 60ch; line-height: 1.5; }
.lp-conf-low { color: var(--hold); }
.lp-vright { text-align: right; }
.lp-figure { font-family: 'Instrument Serif', Georgia, serif; font-size: clamp(2.3rem, 4vw, 3rem); line-height: 1;
  color: var(--ink); font-variant-numeric: tabular-nums; }
.lp-meta { color: var(--faint); font-size: .8rem; margin-top: .55rem; }
.lp-steps { grid-column: 1 / -1; list-style: none; display: flex; margin: .4rem 0 0; padding: 0; counter-reset: s; }
.lp-steps li { flex: 1 1 0; position: relative; padding: 1.05rem .6rem 0 0; min-width: 0; font-size: .76rem; color: var(--ink-2); line-height: 1.35; }
.lp-steps li::before { content: ""; position: absolute; top: 0; left: 0; width: 7px; height: 7px; border-radius: 50%;
  background: var(--accent); box-shadow: 0 0 0 3px var(--bg); z-index: 1; }
.lp-steps li::after { content: ""; position: absolute; top: 3px; left: 11px; right: 4px; height: 1px; background: var(--faint); opacity: .45; }
.lp-steps li:last-child::after { display: none; }
.lp-steps li.bad::before { background: var(--fraud); } .lp-steps li.bad { color: var(--fraud); }
.lp-steps li em { display: block; font-style: normal; color: var(--muted); font-family: 'Geist Mono', monospace; font-size: .7rem; margin-top: .15rem; }
.lp-doc { display: flex; flex-wrap: wrap; gap: .3rem 2rem; margin: 2rem 0 0; padding: .9rem 0; border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line); font-size: .84rem; color: var(--muted); }
.lp-doc span b { display: block; color: var(--ink); font-weight: 500; font-size: .92rem; margin-top: .1rem; }

/* findings: a ruled list */
.lp-findings { border-top: 1px solid var(--line); }
.lp-finding { padding: .9rem 0; border-bottom: 1px solid var(--line); }
.lp-finding .top { display: flex; justify-content: space-between; gap: 1rem; align-items: baseline; }
.lp-finding b { color: var(--ink); font-weight: 500; }
.lp-finding .lp-amt { color: var(--ink); font-family: 'Geist Mono', monospace; font-size: .9rem; white-space: nowrap; }
.lp-finding p { margin: .3rem 0 0; color: var(--muted); font-size: .86rem; line-height: 1.5; }
.lp-code { font-family: 'Geist Mono', monospace; font-size: .7rem; color: var(--faint); background: none; border: 0; padding: 0; margin-left: .5rem; }
.lp-rule { color: var(--faint); font-size: .78rem; margin-top: .2rem; }
.lp-finding.fraud { --tone: var(--fraud); } .lp-finding.err { --tone: var(--muted); }
.lp-clear { padding: 1rem 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.lp-clear p { margin: 0; color: var(--ink); } .lp-clear .lp-small { margin-top: .3rem; }

/* the agent's voice */
.lp-quote { margin: 0; padding: .1rem 0 .1rem 1.1rem; border-left: 1px solid var(--accent); }
.lp-quote p { font-family: 'Instrument Serif', Georgia, serif; font-size: 1.32rem; line-height: 1.32; color: var(--ink); margin: 0; }
.lp-quote ul { list-style: none; margin: .8rem 0 0; padding: 0; }
.lp-quote li { color: var(--muted); font-size: .82rem; padding: .15rem 0; }
.lp-quote li::before { content: "—"; color: var(--faint); margin-right: .5rem; }
.lp-trail { width: 100%; border-collapse: collapse; font-size: .8rem; }
.lp-trail td { padding: .5rem .3rem; border-bottom: 1px solid var(--line); vertical-align: top; color: var(--ink-2); }
.lp-trail td:first-child { padding-left: 0; width: 1rem; }
.lp-trail td.t { text-align: right; white-space: nowrap; color: var(--faint); font-family: 'Geist Mono', monospace; font-size: .74rem; }
.lp-trail .okm { color: var(--ok); } .lp-trail .bad { color: var(--fraud); }

.lp-banner { border-left: 2px solid var(--hold); padding: .35rem 0 .35rem .9rem; margin: 1.4rem 0 0; color: var(--ink-2);
  font-size: .88rem; overflow-wrap: anywhere; }
.lp-banner b { color: var(--hold); font-weight: 500; }

/* ---------- review queue: ledger rows */
.lp-chip { font-size: .78rem; font-weight: 500; white-space: nowrap; }
.lp-chip::before { content: ""; display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: currentColor;
  margin-right: .45rem; transform: translateY(-1px); }
[class*="st-key-q-"] { border-top: 1px solid var(--line); padding: 1.2rem 0 1.1rem; }
.lp-qhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: .3rem 1rem; }
.lp-qhead b { color: var(--ink); font-weight: 500; font-size: 1rem; }
.lp-qmeta { color: var(--muted); font-size: .82rem; margin-top: .25rem; }
.lp-qmeta .lp-num { color: var(--ink-2); }
.lp-qnote { color: var(--ink-2); font-size: .86rem; margin-top: .6rem; line-height: 1.5; max-width: 70ch; }
.lp-qitem { color: var(--muted); font-size: .82rem; margin-top: .25rem; }
[class*="st-key-reject-"] button:hover { color: var(--fraud); border-color: var(--fraud); background: transparent; }

/* ---------- empty states */
.lp-empty { padding: 3.2rem 1rem; text-align: center; color: var(--muted); font-size: .88rem; }
.lp-empty .lp-serif { display: block; color: var(--ink-2); font-size: 1.6rem; margin-bottom: .35rem; }

/* ---------- measured results (markdown tables) */
.st-key-results table { width: 100%; border-collapse: collapse; font-size: .86rem; }
.st-key-results th { color: var(--muted); font-weight: 500; text-align: left; border-bottom: 1px solid var(--line-2); background: none; }
.st-key-results td { border-bottom: 1px solid var(--line); color: var(--ink-2); font-variant-numeric: tabular-nums; }
.st-key-results th, .st-key-results td { border-left: 0; border-right: 0; border-top: 0; padding: .5rem .6rem .5rem 0; }

/* ---------- sidebar */
[data-testid="stSidebarUserContent"] { padding-top: .4rem; }
.lp-brand { display: flex; align-items: center; gap: .6rem; margin: -.6rem 0 1.6rem; color: var(--ink); font-weight: 600; font-size: 1rem; letter-spacing: -.01em; }
.lp-side-h { color: var(--faint); font-size: .74rem; font-weight: 500; margin: 0 0 .5rem; letter-spacing: .02em; }
[data-testid="stSidebar"] [data-testid="stAlertContainer"] { background: transparent !important; border: 0 !important;
  padding: .15rem 0 .15rem 1rem !important; position: relative; }
[data-testid="stSidebar"] [data-testid="stAlertContainer"]::before { content: ""; position: absolute; left: .05rem; top: .62rem;
  width: 6px; height: 6px; border-radius: 50%; background: var(--hold); }
[data-testid="stSidebar"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"])::before { background: var(--ok); }
[data-testid="stSidebar"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"])::before { background: var(--fraud); }
[data-testid="stSidebar"] [data-testid="stAlertContainer"] p { color: var(--ink-2) !important; font-size: .84rem; line-height: 1.5; }
[data-testid="stSidebar"] [data-testid="stAlertContainer"] code { font-size: .74rem; background: none; color: var(--muted); padding: 0; }
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] { font-size: .84rem; min-height: 2.1rem; border-color: var(--line); }
[data-testid="stSidebar"] hr { margin: 1.3rem 0; border-color: var(--line); }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: var(--faint); }
.lp-side-foot { color: var(--faint); font-size: .74rem; line-height: 1.5; margin-top: 2rem; }

@media (max-width: 900px) {
  .lp-ledger { grid-template-columns: 1fr 1fr; }
  .lp-fig { border-left: 0; padding-left: 0; border-top: 1px solid var(--line); }
  .lp-fig:nth-child(-n+2) { border-top: 0; }
  .lp-fig:nth-child(even) { padding-left: 1.1rem; border-left: 1px solid var(--line); }
  .lp-fig:last-child { grid-column: 1 / -1; }
  .lp-conn { border-left: 0; padding-left: 0; margin-top: 1rem; }
}
@media (max-width: 640px) {
  .block-container { padding-left: 1.1rem; padding-right: 1.1rem; padding-top: 2.6rem; }
  .lp-verdict-block { grid-template-columns: 1fr; } .lp-vright { text-align: left; }
  .lp-steps { flex-direction: column; gap: .7rem; }
  .lp-steps li { padding: 0 0 0 1.2rem; } .lp-steps li::before { top: .3rem; }
  .lp-steps li::after { left: 3px; top: 1rem; bottom: -.7rem; right: auto; width: 1px; height: auto; }
  .lp-mixrow { flex-direction: column; align-items: stretch; gap: .5rem; }
}
@media (prefers-reduced-motion: reduce) { .lp-verdict-block, .lp-mix span { animation: none; transition: none; } }
</style>"""
st.markdown("<style>:root { " + "; ".join(f"--{k}: {v}" for k, v in PALETTE[THEME].items()) + " }</style>" + CSS,
            unsafe_allow_html=True)

# A ledger mark: a folded page with two ruled lines
MARK = ('<svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">'
        '<path d="M5 2.75h6.6L15.25 6.4V16.5a.75.75 0 0 1-.75.75h-9.5a.75.75 0 0 1-.75-.75V3.5A.75.75 0 0 1 5 2.75Z" '
        'stroke="var(--accent)" stroke-width="1.3"/><path d="M11.5 2.9V6.5h3.6" stroke="var(--accent)" stroke-width="1.3"/>'
        '<path d="M7 10h6M7 13h4" stroke="var(--ink)" stroke-width="1.3" stroke-linecap="round"/></svg>')


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


TONE = {"approve_for_payment": "ok", "hold_for_review": "hold", "escalate_fraud": "fraud", "processing_error": "err"}


def mix_html(routes: list[str]) -> str:
    """Decision mix as one thin bar with a legend: the shape of the work so far."""
    if not routes:
        return ('<div class="lp-mixrow"><div class="lp-mix"></div>'
                '<div class="lp-legend empty">Decisions appear here as invoices are checked</div></div>')
    counts = {r: routes.count(r) for r in TONE if r in routes}
    bar = "".join(f'<span style="width:{n / len(routes) * 100:.2f}%;background:var(--{TONE[r]})" '
                  f'title="{STAMP[r][0]}: {n}"></span>' for r, n in counts.items())
    legend = "".join(f'<span><i style="background:var(--{TONE[r]})"></i>{STAMP[r][0]} {n}</span>' for r, n in counts.items())
    return f'<div class="lp-mixrow"><div class="lp-mix">{bar}</div><div class="lp-legend">{legend}</div></div>'


# ------------------------------------------------------------------ sidebar
model_problem = settings.model_problem()
health = cached_health(settings.amd_base_url, settings.amd_model) if not model_problem else None

with st.sidebar:
    st.markdown(f'<div class="lp-brand">{MARK}<span>LedgerPilot</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="lp-side-h">Connections</div>', unsafe_allow_html=True)
    if model_problem:
        st.warning(f"AMD model endpoint isn't set up. {model_problem}")
    elif health["ok"]:
        st.success(f"AMD model online on {settings.model_where} ({health['latency_ms']} ms)  \n`{settings.amd_model}`")
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
    if health and health["ok"]:
        if st.button("Measure model speed", width="stretch",
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
            if st.button("Check team usage", width="stretch",
                         help="Asks Token Factory how much of the daily quota your team's shared key has left."):
                st.session_state["usage"] = model_usage(settings)
            usage = st.session_state.get("usage")
            if usage and usage["ok"]:
                with st.expander("Token Factory usage (shared by your team)"):
                    st.json(usage["usage"])
            elif usage:
                st.caption(f"Usage check failed: {usage['detail']}")
    if settings.token_factory:
        st.caption(f"[AMD Token Factory]({TOKEN_FACTORY_SIGN_IN}): one free key per team, shared limits. "
                   "Send only the synthetic sample invoices.")
    st.divider()
    st.markdown('<div class="lp-side-h">Demo</div>', unsafe_allow_html=True)
    recorded_cases = recording.available(settings.recordings_dir)
    # ?demo=1 opens the app in demo mode (a link to hand judges if the live services are down)
    demo_mode = st.toggle("Replay recorded runs", key="demo_mode",
                          value=st.query_params.get("demo") == "1",
                          help="Shows saved outputs of earlier live runs, clearly labelled as recorded. "
                               "Use it if the live services are slow or down.")
    st.caption(f"{len(recorded_cases)} recorded case(s) available." if recorded_cases else
               "No recordings yet. `python eval/run_eval.py` saves one per case, or use "
               "'Save for demo mode' after a live check.")
    if st.button("Clear demo history", width="stretch",
                 help="Empties the audit log so sample invoices can be checked again without being flagged as duplicates."):
        audit.reset()
        st.session_state.pop("result", None)
        st.session_state["toast"] = ("Demo history cleared. Sample invoices can be checked again.", ":material/restart_alt:")
        st.rerun()
    st.markdown('<p class="lp-side-foot">Checks run in Python. Reading, reasoning and actions run on Evolus, '
                + ("with the agent's model on AMD Token Factory." if settings.token_factory else
                   "with the agent's model served by vLLM on an AMD Instinct MI300X.")
                + " Every payment still needs a person's approval.</p>", unsafe_allow_html=True)

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
    model_status = ("on", f'<b>Model:</b> {E(str(health["weights"]))} served on {where}'
                          f' · endpoint answered in {health["latency_ms"]} ms{rate}')
elif health:
    model_status = ("off", f'<b>Model:</b> {E(settings.model_where)} endpoint not reachable')
else:
    model_status = ("warn", "<b>Model:</b> AMD model endpoint not set up (see the sidebar)")
evolus_status = ("warn", "<b>Evolus:</b> not connected") if settings.missing() else ("on", "<b>Evolus:</b> connected")

intro, status_col = st.columns([1.75, 1], gap="large", vertical_alignment="bottom")
intro.markdown('<div class="lp-eyebrow">Accounts payable</div>'
               '<div class="lp-display">Every invoice, checked<br><em>before it is paid.</em></div>',
               unsafe_allow_html=True)
with status_col:
    st.markdown('<div class="lp-conn">' + "".join(f'<div class="row"><span class="lp-dot {s}"></span><span>{t}</span></div>'
                                                  for s, t in (model_status, evolus_status)) + "</div>",
                unsafe_allow_html=True)
    with st.popover("How LedgerPilot decides", type="tertiary"):
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


def fig(key: str, label: str, value: str, sub: str) -> str:
    return (f'<div class="lp-fig"><div class="k">{label}</div>'
            f'<div class="v" data-kpi="{key}">{value}</div><div class="s">{sub}</div></div>')


st.markdown('<section class="lp-ledger">'
            + fig("checked", "Invoices checked", str(checked), "since history was cleared")
            + fig("ready", "Ready to pay", str(ready), "awaiting approval")
            + fig("held", "Held for review", money(held), f"{len(held_rows)} invoice{'s' if len(held_rows) != 1 else ''} on hold")
            + fig("blocked", "Payments blocked", str(blocked), "possible fraud")
            + fig("pending", "Awaiting review", str(pending_count), "in the review queue")
            + "</section>" + mix_html([r["final_route"] for r in rows_all]), unsafe_allow_html=True)

if demo_mode:
    st.markdown('<div class="lp-banner"><b>Demo mode.</b> Results below are replays of recorded live runs, '
                'not live calls to Evolus or the AMD model. Turn it off in the sidebar to check invoices live.</div>',
                unsafe_allow_html=True)

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
    mark = ("background-color: rgba(226,103,79,0.14); color: #F0907C; font-weight: 600" if THEME == "dark" else
            "background-color: rgba(184,67,45,0.09); color: #9C3522; font-weight: 600")

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
    return (f'<div class="lp-finding {tone}"><div class="top"><span><b>{E(FINDING.get(d.code, d.code))}</b>'
            f'<code class="lp-code">{E(d.code)}</code></span>{amount}</div>'
            f'<div class="lp-rule">Rule: {E(RULE.get(d.code, "Rules engine"))} → {E(label.lower())}</div>'
            f'<p>{E(d.message)}</p></div>')


def steps_html(res: CaseResult) -> str:
    """The pipeline as a timeline: one point per step, with its time."""
    items = "".join(f'<li class="{"" if s["ok"] else "bad"}">{E(s["step"])}<em>{s["seconds"]:.1f} s</em></li>' for s in res.steps)
    return f'<ol class="lp-steps">{items}</ol>' if items else ""


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
    n = len(res.discrepancies)
    st.markdown(
        f'<section class="lp-verdict-block"><div><div class="lp-eyebrow">Decision</div>{stamp_html(route)}'
        f'<p class="lp-verdict">{E(sentence)}</p>{conf}</div>'
        f'<div class="lp-vright"><div class="lp-eyebrow" style="justify-content:flex-end">Money at risk</div>'
        f'<div class="lp-figure">{money(res.money_at_risk)}</div>'
        f'<div class="lp-meta">{n} finding{"s" if n != 1 else ""} · decided in {res.timings.get("total_s", 0):.1f} s</div></div>'
        f'{steps_html(res)}</section>', unsafe_allow_html=True)

    if res.error:
        st.error(res.error)
        if res.steps:
            st.markdown(trail_html(res), unsafe_allow_html=True)
        return

    inv = res.extracted.get("invoice") or {}
    st.markdown('<div class="lp-doc">'
                f'<span>Invoice<b class="lp-num">{E(str(inv.get("invoice_number")))}</b></span>'
                f'<span>Supplier<b>{E(str(inv.get("supplier_name") or inv.get("supplier_id")))}</b></span>'
                f'<span>Purchase order<b class="lp-num">{E(str(inv.get("po_number")))}</b></span>'
                f'<span>Total due<b class="lp-num">{money(inv.get("total"))} {E(str(inv.get("currency") or ""))}</b></span>'
                '</div>', unsafe_allow_html=True)

    st.markdown("##### Order, delivery and invoice side by side")
    df = match_table(res)
    if df.empty:
        st.info("No invoice lines could be read.")
    else:
        st.dataframe(style_match(df), hide_index=True, width="stretch")
        st.caption("Highlighted cells differ from the purchase order or the delivery note.")

    left, right = st.columns([1.25, 1], gap="large")
    with left:
        st.markdown("##### What the checks found")
        if res.discrepancies:
            st.markdown('<div class="lp-findings">' + "".join(finding_html(d) for d in res.discrepancies) + "</div>",
                        unsafe_allow_html=True)
            st.caption("Every figure here is calculated by code, not by the language model.")
        else:
            st.markdown('<div class="lp-clear"><p>Nothing to flag. Quantities, prices, totals, supplier and bank account '
                        f'all check out.</p><p class="lp-small">Checks that ran and passed: {E(", ".join(CHECKS_RUN))}.</p></div>',
                        unsafe_allow_html=True)
        with st.expander("Fields read from the documents"):
            st.dataframe(fields_table(res), hide_index=True, width="stretch")
            st.caption("Read by the Evolus document extractors. The bank account is masked on screen.")
    with right:
        st.markdown("##### The agent's note")
        if res.agent:
            evidence = "".join(f"<li>{E(e)}</li>" for e in res.agent.evidence)
            st.markdown(f'<blockquote class="lp-quote"><p>{E(res.agent.explanation)}</p>'
                        f'{"<ul>" + evidence + "</ul>" if evidence else ""}</blockquote>', unsafe_allow_html=True)
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
            st.text_area("Draft email", res.email_draft, height=200, label_visibility="collapsed")
            st.download_button("Download draft", res.email_draft, f"{inv.get('invoice_number') or 'invoice'}_draft.txt",
                               mime="text/plain", key="dl-draft", type="tertiary")
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
    """Scenario button: pick the sample and check it on the next run, in one click."""
    st.session_state["doc_mode"] = "Use a sample case"
    st.session_state["sample_pick"] = option
    st.session_state["run_now"] = True


def replay(case: str) -> bool:
    rec = recording.load(settings.recordings_dir, case)
    if rec is None:
        return False
    st.session_state.update(result=rec[0], result_meta=rec[1], result_case=case)
    return True


SCENARIO = {"case_01": "Everything matches. Expect Ready to pay.",
            "case_07": "Unit price $2 above the PO on 100 chairs. Expect On hold.",
            "case_15": "Correct amounts, new bank account. Expect Payment blocked."}

with tab_check:
    options = sample_options()
    by_case = {f.name: name for name, f in options.items()}
    # ?case=case_07 checks that sample once when the page opens
    if not st.session_state.get("url_case_done") and st.query_params.get("case") in by_case:
        st.session_state["url_case_done"] = True
        queue_case(by_case[st.query_params["case"]])
    rehearsal = [(case, text) for case, text in REHEARSAL if case in by_case]
    side, main = st.columns([1, 1.85], gap="large") if rehearsal else (None, st.container())
    if side is not None:
        with side:
            st.markdown('<div class="lp-h">Try a scenario</div>'
                        '<p class="lp-sub">Rehearsed cases. One click runs the full check.</p>', unsafe_allow_html=True)
            for case, text in rehearsal:
                st.button(text, key=f"scn-{case}", on_click=queue_case, args=(by_case[case],), width="stretch",
                          help=case.replace("_", " ").capitalize())
                st.markdown(f'<p class="lp-scn">{E(SCENARIO.get(case, ""))}</p>', unsafe_allow_html=True)
    with main:
        with st.container(key="docs-panel"):
            mode = st.radio("Documents", ["Use a sample case", "Upload my own"], horizontal=True, key="doc_mode")
            docs, label = None, ""
            if mode == "Use a sample case":
                if not options:
                    st.warning("No sample cases found. Run `python scripts/make_samples.py` first.")
                else:
                    pick = st.selectbox("Sample case", list(options), key="sample_pick")
                    folder = options[pick]
                    c0, c1, c2, c3 = st.columns([1.1, 1, 1, 0.8], vertical_alignment="center")
                    c0.markdown('<p class="lp-srcs">Source documents</p>', unsafe_allow_html=True)
                    for col, (kind, name) in zip((c1, c2, c3), (("po", "Purchase order"), ("grn", "Delivery note"),
                                                                ("invoice", "Invoice")), strict=True):
                        col.download_button(name, (folder / f"{kind}.pdf").read_bytes(), f"{folder.name}_{kind}.pdf",
                                            mime="application/pdf", key=f"dl-{kind}", type="tertiary",
                                            help=f"Download the {name.lower()} PDF")
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
            clicked = st.button("Replay recorded result" if demo_mode else "Check invoice", type="primary",
                                key="check-btn", disabled=docs is None)

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
            st.button("Show the recorded run of this case instead", key="fallback",
                      help="Replays a saved live run, clearly labelled as recorded.", on_click=replay, args=(case,))
        if meta is None and res.route is not Route.ERROR and case in by_case:
            if st.button("Save for demo mode", key="save-rec", type="tertiary",
                         help="Stores this live result so demo mode can replay it, labelled as recorded."):
                try:
                    recording.save(settings.recordings_dir, res, case,
                                   model=(health or {}).get("weights") or settings.amd_model, source="app, live check")
                    st.success(f"Saved. Demo mode will replay this run of {case}.")
                except OSError as exc:
                    st.error(f"Couldn't save the recording ({type(exc).__name__}). Check RECORDINGS_DIR is writable.")
    else:
        st.markdown('<div class="lp-empty"><span class="lp-serif">Nothing checked yet</span>Run a scenario, or choose a '
                    'sample and press Check invoice. The decision and its evidence appear here.</div>',
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
        st.markdown('<div class="lp-empty"><span class="lp-serif">The queue is clear</span>Every checked invoice lands '
                    'here, and nothing is paid until a person releases it.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="lp-h">{len(pending)} invoice{"s" if len(pending) != 1 else ""} waiting</div>'
                    '<p class="lp-sub">Newest first. Release only what you have checked; a blocked payment needs a note '
                    'saying how the supplier was verified.</p>', unsafe_allow_html=True)
    for row in pending:
        with st.container(key=f"q-{row['final_route']}-{row['id']}"):
            info, act = st.columns([2.6, 1], gap="large")
            info.markdown(f'<div class="lp-qhead"><b class="lp-num">{E(str(row["invoice_number"] or row["label"]))}</b>'
                          f'{chip(row["final_route"])}</div>'
                          f'<div class="lp-qmeta">{E(str(row["supplier_id"] or "unknown supplier"))} · '
                          f'total <span class="lp-num">{money(row["total"])} {E(str(row["currency"] or ""))}</span> · '
                          f'at risk <span class="lp-num">{money(row["money_at_risk"])}</span> · '
                          f'checked {E(str(row["created_at"] or "")[:16].replace("T", " "))}</div>',
                          unsafe_allow_html=True)
            if row["explanation"]:
                info.markdown(f'<div class="lp-qnote">{E(row["explanation"])}</div>', unsafe_allow_html=True)
            if row["error"]:
                info.markdown(f'<div class="lp-qitem">{E(row["error"])}</div>', unsafe_allow_html=True)
            for d in json.loads(row["discrepancies"] or "[]"):
                info.markdown(f'<div class="lp-qitem">{E(FINDING.get(d["code"], d["code"]))}: {E(d["message"])}</div>',
                              unsafe_allow_html=True)
            blocked_row = row["final_route"] == "escalate_fraud"
            act.text_input("Reviewer note", key=f"note{row['id']}",
                           placeholder="Required to release a blocked payment" if blocked_row else "Optional note")
            if row["final_route"] == "processing_error":
                # An invoice that could not be read can never be released from here.
                act.caption("Can't be paid from here. Check the documents by hand or upload readable copies.")
            else:
                act.button("Release for payment", key=f"release-{row['id']}", on_click=review_case,
                           args=(row["id"], "approved_by_reviewer", blocked_row), width="stretch")
                if note_missing == row["id"]:
                    act.error("Add a note saying how the supplier was verified.")
            act.button("Reject invoice", key=f"reject-{row['id']}", on_click=review_case,
                       args=(row["id"], "rejected_by_reviewer"), width="stretch")


# ------------------------------------------------------------------ audit log
def exposure_chart(df: pd.DataFrame):
    """Money held or blocked, accumulated in the order invoices were checked."""
    d = df.sort_values("id").copy()
    d["stopped"] = d.apply(lambda r: float(r["money_at_risk"] or 0) if r["final_route"] in ("hold_for_review", "escalate_fraud")
                           else 0.0, axis=1).cumsum()
    d["check"] = range(1, len(d) + 1)
    c = PALETTE[THEME]
    base = alt.Chart(d).encode(
        x=alt.X("check:Q", title=None, axis=alt.Axis(tickMinStep=1, format="d", grid=False, labelColor=c["faint"],
                                                    domainColor=c["line"], tickColor=c["line"])),
        y=alt.Y("stopped:Q", title=None, axis=alt.Axis(gridColor=c["line"], domain=False, ticks=False,
                                                      labelColor=c["faint"], format=",.0f", tickCount=4)))
    area = base.mark_area(color=c["accent"], opacity=0.10, interpolate="step-after")
    line = base.mark_line(color=c["accent"], strokeWidth=1.6, interpolate="step-after")
    points = base.mark_circle(color=c["accent"], size=28).encode(
        tooltip=[alt.Tooltip("check:Q", title="Check"), alt.Tooltip("invoice_number:N", title="Invoice"),
                 alt.Tooltip("stopped:Q", title="Stopped so far", format=",.2f")])
    return ((area + line + points).properties(height=170, background="transparent")
            .configure_view(strokeWidth=0).configure(font="Geist"))


with tab_audit:
    rows = audit.all()
    if not rows:
        st.markdown('<div class="lp-empty"><span class="lp-serif">No history yet</span>Every check is recorded here with '
                    'its decision and Evolus run IDs.</div>', unsafe_allow_html=True)
    else:
        df = pd.DataFrame(rows)
        df["Decision"] = df["final_route"].map(lambda r: STAMP.get(r, (r,))[0])
        stopped_total = sum(Decimal(str(r["money_at_risk"] or 0)) for r in rows
                            if r["final_route"] in ("hold_for_review", "escalate_fraud"))
        chart_col, mix_col = st.columns([1.8, 1], gap="large")
        with chart_col:
            st.markdown(f'<div class="lp-h">Money stopped before payment</div><p class="lp-sub">'
                        f'<span class="lp-num" style="color:var(--ink)">{money(stopped_total)}</span> held or blocked across '
                        f'{len(rows)} check{"s" if len(rows) != 1 else ""}, accumulated in the order they ran.</p>',
                        unsafe_allow_html=True)
            if len(rows) > 1:
                st.altair_chart(exposure_chart(df), width="stretch")
        with mix_col:
            st.markdown('<div class="lp-h">Decision mix</div><p class="lp-sub">Share of every invoice checked.</p>'
                        + mix_html([r["final_route"] for r in rows]), unsafe_allow_html=True)
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
        st.dataframe(view, hide_index=True, width="stretch")
        st.download_button("Download audit log (CSV)", view.to_csv(index=False), "ledgerpilot_audit.csv", mime="text/csv",
                           type="tertiary")


# ------------------------------------------------------------------ results
with tab_results:
    with st.container(key="results"):
        shown = False
        for name in ("evaluation.md", "benchmark.md"):
            path = ROOT / "docs" / name
            if path.exists():
                st.markdown(path.read_text())
                shown = True
        if not shown:
            st.markdown('<div class="lp-empty"><span class="lp-serif">No measured results yet</span>Run '
                        '<code>python eval/run_eval.py</code> and <code>python scripts/benchmark_amd.py</code> once the AMD '
                        'endpoint and Evolus are connected; the tables appear here.</div>', unsafe_allow_html=True)
