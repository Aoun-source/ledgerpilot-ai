"""LedgerPilot AI - Streamlit front end.

    streamlit run app.py
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import tempfile
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ledgerpilot import recording  # noqa: E402
from ledgerpilot.agent_client import ClerkAgent, model_health, model_speed, model_usage  # noqa: E402
from ledgerpilot.audit import AuditLog  # noqa: E402
from ledgerpilot.config import TOKEN_FACTORY_SIGN_IN, ConfigError, load_settings  # noqa: E402
from ledgerpilot.fraud import mask, mask_accounts  # noqa: E402
from ledgerpilot.pipeline import CaseResult, Pipeline, load_case_folder  # noqa: E402
from ledgerpilot.schemas import Route  # noqa: E402

st.set_page_config(page_title="LedgerPilot", page_icon=":material/receipt_long:", layout="wide",
                   initial_sidebar_state="auto")

SAMPLES = ROOT / "data" / "samples"
E = html.escape  # everything from documents or the model is escaped before it touches HTML

STAMP = {
    "approve_for_payment": ("Ready to pay", "ok", "Purchase order, delivery and invoice agree. A person gives the final yes in the review queue."),
    "hold_for_review": ("Needs review", "hold", "Payment is held until the supplier explains or corrects the invoice."),
    "escalate_fraud": ("Payment blocked", "fraud", "Possible fraud. Nothing is paid until a manager verifies the supplier by phone."),
    "processing_error": ("Needs a person", "err", "This invoice could not be checked automatically."),
}
NEXT_STEP = {
    "approve_for_payment": "Give it a final look and release it for payment from the review queue.",
    "hold_for_review": "Send the draft query to the supplier and keep the payment on hold until they reply.",
    "escalate_fraud": "Call the supplier on the phone number in the vendor master, never the one on the invoice, before anything is paid.",
    "processing_error": "Check the documents by hand, or upload clearer copies and run the check again.",
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
# One click loads and checks the cases rehearsed for the demo: (case, title, expected route, description)
REHEARSAL = (
    ("case_01", "Clean invoice", "approve_for_payment", "Order, delivery and invoice all agree."),
    ("case_07", "Overcharged by $200", "hold_for_review", "Unit price $2 above the PO on 100 chairs."),
    ("case_15", "Bank account changed", "escalate_fraud", "Correct amounts, but a new pay-to bank account."),
)
TONE = {"approve_for_payment": "ok", "hold_for_review": "hold", "escalate_fraud": "fraud", "processing_error": "err"}

# Design tokens. Each status has a strong colour (bars, borders), a darker ink (text on white) and a soft tint.
PALETTE = {"bg": "#F4F7FB", "surface": "#FFFFFF", "raised": "#F7F9FC", "line": "#DFE7F0", "line-2": "#CBD6E2",
           "ink": "#183153", "ink-2": "#33496A", "muted": "#63748B", "faint": "#8796AA",
           "accent": "#07966F", "accent-2": "#057A5B", "accent-soft": "#E5F5EF", "info": "#3478F6", "info-soft": "#EAF1FE",
           "ok": "#07966F", "ok-ink": "#057A5B", "ok-soft": "#E5F5EF",
           "hold": "#F5B942", "hold-ink": "#8A5A00", "hold-soft": "#FEF6E4",
           "fraud": "#E5485D", "fraud-ink": "#C0303F", "fraud-soft": "#FDECEE",
           "err": "#63748B", "err-ink": "#3D4F66", "err-soft": "#EEF2F7",
           "shadow": "0 1px 2px rgba(24,49,83,.05), 0 4px 16px -8px rgba(24,49,83,.10)"}

# Lucide icons (MIT), inlined so the page needs no icon font
ICON = {
    "file-check": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="m9 15 2 2 4-4"/>',
    "ok": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "hold": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "fraud": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m14.5 9.5-5 5"/><path d="m9.5 9.5 5 5"/>',
    "err": '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    "inbox": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "bot": '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
    "user-check": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><polyline points="16 11 18 13 22 9"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "history": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
}


def icon(name: str, size: int = 18, cls: str = "") -> str:
    return (f'<svg class="lp-ic {cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICON[name]}</svg>')


CSS = r"""
<style>
/* ---------- canvas and type */
.block-container { padding-top: 2.4rem; padding-bottom: 4rem; max-width: 1240px; }
::selection { background: var(--accent-soft); }
.lp-num { font-variant-numeric: tabular-nums; }
.lp-ic { flex: none; display: inline-block; vertical-align: middle; }
.lp-muted { color: var(--muted); }

/* page header */
.lp-page { margin: 0 0 1.6rem; }
.lp-page h1 { font-size: 30px; line-height: 1.2; font-weight: 700; letter-spacing: -.02em; color: var(--ink); margin: 0; padding: 0; }
.lp-page p { color: var(--muted); font-size: 15px; margin: .35rem 0 0; }
[data-testid="stMarkdownContainer"] .lp-page p { font-size: 15px; }
.lp-section { font-size: 19px; font-weight: 600; color: var(--ink); margin: 0 0 .25rem; letter-spacing: -.01em; }
.lp-section-sub { color: var(--muted); font-size: 14px; margin: 0 0 1rem; line-height: 1.5; }
[data-testid="stMarkdownContainer"] p.lp-section-sub { font-size: 14px; margin: 0 0 1rem; }
.block-container h5 { font-size: 16px !important; font-weight: 600 !important; color: var(--ink) !important;
  margin: 1.6rem 0 .6rem; padding: 0; letter-spacing: -.005em; }

/* ---------- cards */
.lp-card, [class*="st-key-card-"] { background: var(--surface); border: 1px solid var(--line); border-radius: 14px;
  box-shadow: var(--shadow); }
.lp-card { padding: 1.2rem 1.3rem; }
[class*="st-key-card-"] { padding: 1.2rem 1.3rem 1.3rem; }
[class*="st-key-card-"] [data-testid="stVerticalBlock"] { gap: .75rem; }

/* ---------- KPI cards */
.lp-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1rem; margin: 0 0 1.25rem; }
.lp-kpi { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow);
  padding: 1.05rem 1.15rem 1.1rem; position: relative; min-width: 0; }
.lp-kpi .top { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
.lp-kpi .k { color: var(--muted); font-size: 14px; font-weight: 500; }
.lp-kpi .badge { width: 34px; height: 34px; border-radius: 9px; display: grid; place-items: center; }
.lp-kpi .v { color: var(--ink); font-size: 32px; font-weight: 700; letter-spacing: -.02em; line-height: 1.15; margin-top: .5rem;
  font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lp-kpi .s { color: var(--muted); font-size: 13px; margin-top: .15rem; }
.tone-ok .badge { background: var(--ok-soft); color: var(--ok-ink); }
.tone-hold .badge { background: var(--hold-soft); color: var(--hold-ink); }
.tone-fraud .badge { background: var(--fraud-soft); color: var(--fraud-ink); }
.tone-info .badge { background: var(--info-soft); color: var(--info); }

/* ---------- status pills (text + icon, never colour alone) */
.lp-pill { display: inline-flex; align-items: center; gap: .35rem; font-size: 13px; font-weight: 600; padding: .2rem .6rem .2rem .45rem;
  border-radius: 999px; white-space: nowrap; line-height: 1.4; }
.lp-pill.lp-ok { background: var(--ok-soft); color: var(--ok-ink); }
.lp-pill.lp-hold { background: var(--hold-soft); color: var(--hold-ink); }
.lp-pill.lp-fraud { background: var(--fraud-soft); color: var(--fraud-ink); }
.lp-pill.lp-err { background: var(--err-soft); color: var(--err-ink); }

/* ---------- recent decisions list */
.lp-list { margin: 0; padding: 0; list-style: none; }
.lp-list li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .2rem 1rem; align-items: center;
  padding: .8rem 0; border-top: 1px solid var(--line); }
.lp-list li:first-child { border-top: 0; padding-top: .2rem; }
.lp-list .inv { color: var(--ink); font-weight: 600; font-size: 14.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lp-list .sup { color: var(--muted); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lp-list .amt { color: var(--ink); font-weight: 600; font-size: 14px; text-align: right; font-variant-numeric: tabular-nums; }
.lp-list .r { display: flex; flex-direction: column; align-items: flex-end; gap: .25rem; }

/* ---------- empty states */
.lp-empty { padding: 2.2rem 1rem; text-align: center; color: var(--muted); font-size: 14px; line-height: 1.55; }
.lp-empty .ic { width: 44px; height: 44px; border-radius: 12px; background: var(--raised); border: 1px solid var(--line);
  display: grid; place-items: center; margin: 0 auto .8rem; color: var(--muted); }
.lp-empty b { display: block; color: var(--ink); font-size: 16px; font-weight: 600; margin-bottom: .2rem; }

/* ---------- how it decides */
.lp-flow { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: .75rem; margin: 0; padding: 0; list-style: none; counter-reset: s; }
.lp-flow li { counter-increment: s; background: var(--raised); border: 1px solid var(--line); border-radius: 12px; padding: .8rem .85rem; }
.lp-flow li::before { content: counter(s); display: grid; place-items: center; width: 22px; height: 22px; border-radius: 50%;
  background: var(--accent-soft); color: var(--accent-2); font-size: 12px; font-weight: 700; margin-bottom: .5rem; }
.lp-flow b { display: block; color: var(--ink); font-size: 13.5px; font-weight: 600; line-height: 1.35; }
.lp-flow span { display: block; color: var(--muted); font-size: 12.5px; margin-top: .25rem; line-height: 1.4; }

/* ---------- buttons and inputs */
[data-testid="stBaseButton-primary"] { font-weight: 600; box-shadow: 0 1px 2px rgba(7,150,111,.25); }
[data-testid="stBaseButton-primary"]:hover { background: var(--accent-2); border-color: var(--accent-2); }
[data-testid="stBaseButton-primary"]:disabled { background: #E8EEF5; border-color: var(--line); color: var(--faint); box-shadow: none; }
[data-testid="stBaseButton-secondary"] { background: var(--surface); border-color: var(--line-2); color: var(--ink); font-weight: 500; }
[data-testid="stBaseButton-secondary"]:hover { border-color: var(--accent); color: var(--accent-2); background: var(--surface); }
[data-testid="stBaseButton-tertiary"] { color: var(--info); font-weight: 500; }
button:focus-visible, a:focus-visible, [role="radio"]:focus-visible { outline: 2px solid var(--info) !important; outline-offset: 2px; }
[data-testid="stWidgetLabel"] p { color: var(--ink-2); font-size: 13.5px; font-weight: 600; }
[data-testid="stFileUploaderDropzone"] { background: var(--raised); border: 1.5px dashed var(--line-2); }
[data-testid="stExpander"] details { background: var(--surface); border-color: var(--line); border-radius: 12px; }
[data-testid="stExpander"] summary p { font-size: 14.5px; font-weight: 600; color: var(--ink); }
[data-testid="stMain"] [data-testid="stAlertContainer"] { border-radius: 10px; }
[data-testid="stToast"] { background: var(--surface); border: 1px solid var(--line); box-shadow: var(--shadow); }

/* ---------- scenario cards */
[class*="st-key-scard-"] { background: var(--surface); border: 1px solid var(--line); border-top: 4px solid var(--tone);
  border-radius: 14px; padding: 1rem 1.05rem 1.05rem; box-shadow: var(--shadow); height: 100%; transition: border-color .15s ease, box-shadow .15s ease; }
[class*="st-key-scard-"]:hover { box-shadow: 0 2px 4px rgba(24,49,83,.06), 0 10px 24px -12px rgba(24,49,83,.22); }
[class*="st-key-scard-ok-"] { --tone: var(--ok); --tone-ink: var(--ok-ink); --tone-soft: var(--ok-soft); }
[class*="st-key-scard-hold-"] { --tone: var(--hold); --tone-ink: var(--hold-ink); --tone-soft: var(--hold-soft); }
[class*="st-key-scard-fraud-"] { --tone: var(--fraud); --tone-ink: var(--fraud-ink); --tone-soft: var(--fraud-soft); }
[class*="st-key-scard-"][class*="-sel"] { background: var(--tone-soft); border-color: var(--tone); box-shadow: 0 0 0 1px var(--tone) inset; }
.lp-scn-head { display: flex; align-items: center; gap: .55rem; color: var(--tone-ink); }
.lp-scn-head b { color: var(--ink); font-size: 15.5px; font-weight: 600; }
.lp-scn-desc { color: var(--muted); font-size: 13.5px; margin: .4rem 0 .55rem; line-height: 1.45; min-height: 2.6em; }
.lp-scn-exp { display: flex; flex-wrap: wrap; align-items: center; gap: .35rem .5rem; font-size: 12.5px; color: var(--muted); }
.lp-scn-sel { font-size: 12.5px; font-weight: 600; color: var(--tone-ink); }
[class*="st-key-scard-"] button { width: 100%; }

/* ---------- decision summary */
.lp-decision { border: 1px solid var(--line); border-left: 5px solid var(--tone); border-radius: 14px; background: var(--surface);
  box-shadow: var(--shadow); padding: 1.3rem 1.4rem; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 1rem 2rem;
  margin: 1.6rem 0 0; animation: lp-in .3s ease-out 1; }
@keyframes lp-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
.lp-decision.ok { --tone: var(--ok); --tone-ink: var(--ok-ink); --tone-soft: var(--ok-soft); }
.lp-decision.hold { --tone: var(--hold); --tone-ink: var(--hold-ink); --tone-soft: var(--hold-soft); }
.lp-decision.fraud { --tone: var(--fraud); --tone-ink: var(--fraud-ink); --tone-soft: var(--fraud-soft); }
.lp-decision.err { --tone: var(--err); --tone-ink: var(--err-ink); --tone-soft: var(--err-soft); }
.lp-eyebrow { color: var(--muted); font-size: 12.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; margin: 0 0 .4rem; }
.lp-stamp-row { display: flex; align-items: center; gap: .6rem; color: var(--tone-ink); }
.lp-stamp { font-size: 28px; font-weight: 700; letter-spacing: -.02em; line-height: 1.15; color: var(--tone-ink); }
.lp-verdict { color: var(--ink); font-size: 15.5px; margin: .55rem 0 0; max-width: 62ch; line-height: 1.55; overflow-wrap: anywhere; }
.lp-conf { color: var(--muted); font-size: 14px; margin: .35rem 0 0; max-width: 64ch; line-height: 1.5; }
.lp-conf-low { color: var(--hold-ink); font-weight: 500; }
.lp-vright { text-align: right; }
.lp-figure { font-size: 32px; font-weight: 700; color: var(--ink); font-variant-numeric: tabular-nums; letter-spacing: -.02em; line-height: 1.15; }
.lp-meta { color: var(--muted); font-size: 13px; margin-top: .3rem; }
.lp-next { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem; }
.lp-next div { display: flex; gap: .6rem; align-items: flex-start; background: var(--raised); border: 1px solid var(--line);
  border-radius: 10px; padding: .7rem .8rem; font-size: 14px; color: var(--ink-2); line-height: 1.45; }
.lp-next div b { display: block; color: var(--ink); font-size: 13px; margin-bottom: .1rem; }
.lp-next .lp-ic { margin-top: .1rem; color: var(--tone-ink); }
.lp-next .human .lp-ic { color: var(--info); }
.lp-doc { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .75rem; margin: 1rem 0 0; }
.lp-doc span { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: .7rem .9rem; font-size: 13px; color: var(--muted); min-width: 0; }
.lp-doc span b { display: block; color: var(--ink); font-weight: 600; font-size: 15px; margin-top: .15rem; overflow-wrap: anywhere; }

/* findings */
.lp-finding { padding: .85rem .95rem; border: 1px solid var(--line); border-left: 4px solid var(--tone, var(--hold)); border-radius: 10px;
  background: var(--surface); margin-bottom: .6rem; }
.lp-finding.hold { --tone: var(--hold); } .lp-finding.fraud { --tone: var(--fraud); } .lp-finding.err { --tone: var(--err); }
.lp-finding .top { display: flex; justify-content: space-between; gap: 1rem; align-items: baseline; }
.lp-finding b { color: var(--ink); font-weight: 600; font-size: 14.5px; }
.lp-finding .lp-amt { color: var(--ink); font-weight: 600; font-size: 14px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.lp-finding p { margin: .3rem 0 0; color: var(--ink-2); font-size: 14px; line-height: 1.5; }
[data-testid="stMarkdownContainer"] .lp-finding p { font-size: 14px; margin: .3rem 0 0; }
.lp-code { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11.5px; color: var(--muted); background: var(--raised);
  border: 1px solid var(--line); border-radius: 5px; padding: .05rem .35rem; margin-left: .5rem; }
.lp-rule { color: var(--muted); font-size: 13px; margin-top: .25rem; }
.lp-clear { padding: .9rem 1rem; border: 1px solid var(--line); border-left: 4px solid var(--ok); border-radius: 10px; background: var(--surface); }
.lp-clear p { margin: 0; color: var(--ink); font-size: 14.5px; }
[data-testid="stMarkdownContainer"] .lp-clear p { font-size: 14.5px; }
[data-testid="stMarkdownContainer"] .lp-clear p.lp-small { font-size: 13px; color: var(--muted); margin-top: .35rem; }

/* the agent's note */
.lp-quote { margin: 0; padding: .9rem 1rem; border: 1px solid var(--line); border-radius: 10px; background: var(--info-soft); }
.lp-quote .who { display: flex; align-items: center; gap: .45rem; color: var(--info); font-size: 12.5px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .05em; margin-bottom: .45rem; }
.lp-quote p { font-size: 15px; line-height: 1.55; color: var(--ink); margin: 0; }
[data-testid="stMarkdownContainer"] .lp-quote p { font-size: 15px; }
.lp-quote ul { margin: .6rem 0 0; padding-left: 1.1rem; }
.lp-quote li { color: var(--ink-2); font-size: 13.5px; padding: .1rem 0; }

/* what ran, where */
.lp-trail { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.lp-trail td { padding: .5rem .4rem; border-bottom: 1px solid var(--line); vertical-align: top; color: var(--ink-2); }
.lp-trail td:first-child { padding-left: 0; width: 1.2rem; }
.lp-trail td.t { text-align: right; white-space: nowrap; color: var(--muted); font-variant-numeric: tabular-nums; }
.lp-trail .okm { color: var(--ok-ink); font-weight: 700; } .lp-trail .bad { color: var(--fraud-ink); font-weight: 700; }
.lp-small { color: var(--muted); font-size: 13px; }

.lp-banner { display: flex; gap: .6rem; align-items: flex-start; background: var(--info-soft); border: 1px solid #C9DAFB;
  border-radius: 10px; padding: .7rem .9rem; margin: 0 0 1.2rem; color: var(--ink-2); font-size: 14px; overflow-wrap: anywhere; }
.lp-banner b { color: var(--ink); }
.lp-banner .lp-ic { color: var(--info); margin-top: .1rem; }

/* ---------- review queue */
[class*="st-key-q-"] { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow);
  padding: 1.1rem 1.2rem; margin-bottom: .2rem; }
.lp-qhead { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem .8rem; }
.lp-qhead b { color: var(--ink); font-weight: 700; font-size: 16px; }
.lp-qmeta { color: var(--muted); font-size: 13.5px; margin-top: .35rem; }
.lp-qmeta .lp-num { color: var(--ink); font-weight: 600; }
.lp-qnote { color: var(--ink-2); font-size: 14px; margin-top: .6rem; line-height: 1.5; max-width: 75ch; }
.lp-qitem { color: var(--ink-2); font-size: 13.5px; margin-top: .3rem; padding-left: .7rem; border-left: 2px solid var(--line-2); }
[class*="st-key-reject-"] button:hover { color: var(--fraud-ink); border-color: var(--fraud); }

/* ---------- measured results (markdown tables) */
.st-key-card-results table { width: 100%; border-collapse: collapse; font-size: 14px; }
.st-key-card-results th { color: var(--muted); font-weight: 600; text-align: left; border-bottom: 1px solid var(--line-2); background: var(--raised); }
.st-key-card-results td { border-bottom: 1px solid var(--line); color: var(--ink-2); font-variant-numeric: tabular-nums; }
.st-key-card-results th, .st-key-card-results td { border-left: 0; border-right: 0; border-top: 0; padding: .5rem .6rem; }

/* ---------- settings */
.lp-kv { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .2rem 1rem; padding: .6rem 0; border-top: 1px solid var(--line); font-size: 14px; }
.lp-kv:first-of-type { border-top: 0; }
.lp-kv span { color: var(--ink-2); } .lp-kv em { font-style: normal; font-weight: 600; }
.lp-kv em.on { color: var(--ok-ink); } .lp-kv em.off { color: var(--hold-ink); }

/* ---------- sidebar: brand, navigation, connections */
[data-testid="stSidebar"] { min-width: 272px !important; max-width: 272px !important; }
[data-testid="stSidebarUserContent"] { padding-top: .2rem; }
.lp-brand { display: flex; align-items: center; gap: .65rem; margin: -1.4rem 0 1.4rem; }
.lp-brand .logo { width: 34px; height: 34px; border-radius: 9px; background: var(--accent); display: grid; place-items: center; }
.lp-brand b { display: block; color: var(--ink); font-weight: 700; font-size: 17px; letter-spacing: -.01em; line-height: 1.1; }
.lp-brand span { display: block; color: var(--muted); font-size: 12.5px; }
.lp-side-h { color: var(--faint); font-size: 11.5px; font-weight: 700; margin: 0 0 .45rem .2rem; letter-spacing: .08em; text-transform: uppercase; }
.st-key-nav [role="radiogroup"] { gap: .15rem; width: 100%; }
.st-key-nav [data-testid="stWidgetLabel"] { display: none; }
.st-key-nav [role="radiogroup"] > div { width: 100%; }
.st-key-nav [data-testid="stRadioOption"] { width: 100%; margin: 0; padding: .55rem .7rem; border-radius: 9px; cursor: pointer;
  transition: background-color .12s ease; }
.st-key-nav [data-testid="stRadioOption"] > div > div:first-child:not([data-testid]) { display: none; }
.st-key-nav [data-testid="stRadioOption"] p { font-size: 14.5px; font-weight: 500; color: var(--ink-2); }
.st-key-nav [data-testid="stRadioOption"] p span[role="img"] { font-size: 19px; margin-right: .45rem; color: var(--muted); }
.st-key-nav [data-testid="stRadioOption"]:hover { background: var(--raised); }
.st-key-nav [data-testid="stRadioOption"][data-selected="true"] { background: var(--accent-soft); }
.st-key-nav [data-testid="stRadioOption"][data-selected="true"] p,
.st-key-nav [data-testid="stRadioOption"][data-selected="true"] p span[role="img"] { color: var(--accent-2); font-weight: 600; }
.st-key-nav [data-testid="stRadioOption"]:has(input:focus-visible) { outline: 2px solid var(--accent); outline-offset: -2px; }
[data-testid="stSidebar"] hr { margin: 1.1rem 0; border-color: var(--line); }
.lp-conn { display: flex; flex-direction: column; gap: .5rem; }
.lp-conn .row { display: grid; grid-template-columns: 10px minmax(0, 1fr); gap: .55rem; align-items: start; background: var(--raised);
  border: 1px solid var(--line); border-radius: 10px; padding: .55rem .65rem; }
.lp-conn .row b { display: flex; justify-content: space-between; gap: .4rem; color: var(--ink); font-size: 13.5px; font-weight: 600; }
.lp-conn .row b em { font-style: normal; font-size: 12px; font-weight: 600; }
.lp-conn .row small { display: block; color: var(--muted); font-size: 12.5px; line-height: 1.4; margin-top: .1rem; overflow-wrap: anywhere; }
.lp-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: .35rem; background: var(--faint); }
.lp-dot.on { background: var(--ok); box-shadow: 0 0 0 3px var(--ok-soft); } .lp-dot.warn { background: var(--hold); box-shadow: 0 0 0 3px var(--hold-soft); }
.lp-dot.off { background: var(--fraud); box-shadow: 0 0 0 3px var(--fraud-soft); }
.lp-conn em.on { color: var(--ok-ink); } .lp-conn em.warn { color: var(--hold-ink); } .lp-conn em.off { color: var(--fraud-ink); }
[data-testid="stSidebar"] [data-testid="stAlertContainer"] p { font-size: 13px; line-height: 1.5; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary p { font-size: 13.5px; }
.lp-side-foot { color: var(--muted); font-size: 12.5px; line-height: 1.5; margin-top: 1rem; }
[data-testid="stMarkdownContainer"] p.lp-side-foot { font-size: 12.5px; margin-top: 1rem; }
.st-key-go-check button, .st-key-go-chat button { white-space: nowrap; }
.lp-agent-head { display: flex; gap: .9rem; align-items: flex-start; }
.lp-agent-head .ic { flex: none; width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center;
  background: var(--accent-soft); color: var(--accent-2); }
.lp-agent-head .lp-section { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
.lp-agent-head .lp-section-sub { margin-bottom: 0; }
.st-key-card-agent button p { font-size: 13.5px; }

@media (max-width: 1100px) { .lp-flow { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 900px) {
  .lp-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .lp-doc { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .lp-next { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 3.6rem; }
  .lp-page h1 { font-size: 26px; }
  .lp-kpis, .lp-doc, .lp-flow { grid-template-columns: 1fr; }
  .lp-decision { grid-template-columns: 1fr; } .lp-vright { text-align: left; }
}
@media (prefers-reduced-motion: reduce) { .lp-decision { animation: none; } }
</style>"""
st.markdown("<style>:root { " + "; ".join(f"--{k}: {v}" for k, v in PALETTE.items()) + " }</style>" + CSS,
            unsafe_allow_html=True)

LOGO = ('<svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">'
        '<path d="M5 2.75h6.6L15.25 6.4V16.5a.75.75 0 0 1-.75.75h-9.5a.75.75 0 0 1-.75-.75V3.5A.75.75 0 0 1 5 2.75Z" '
        'stroke="#fff" stroke-width="1.5"/><path d="M11.5 2.9V6.5h3.6" stroke="#fff" stroke-width="1.5"/>'
        '<path d="m7.2 11.4 1.8 1.8 3.8-3.8" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')


# ------------------------------------------------------------------ setup
@st.cache_resource
def get_settings():
    # On Streamlit Cloud the keys live in the app's Secrets (server side, never sent to the browser).
    # Copy plain top-level values into the environment, where the settings are read; .env still wins locally.
    try:
        for key, value in st.secrets.items():
            if isinstance(value, (str, int, float, bool)):
                os.environ.setdefault(key, str(value))
    except Exception:  # noqa: BLE001 - no secrets file is the normal local case
        pass
    return load_settings()


try:
    settings = get_settings()
except ConfigError as exc:
    st.error(f"Configuration problem: {exc}")
    st.stop()
if settings.public_site:
    # Public demo: each visitor gets a private history, so one person's checks never show up for another
    # (or turn the next visitor's sample invoice into a "duplicate").
    st.session_state.setdefault("audit_db", str(Path(tempfile.gettempdir()) / f"ledgerpilot_{uuid.uuid4().hex}.db"))
    audit = AuditLog(st.session_state["audit_db"])
else:
    audit = AuditLog(settings.audit_db)


@st.cache_resource
def _shared_pipeline():
    return Pipeline(settings, audit)


def get_pipeline():
    if not settings.public_site:
        return _shared_pipeline()
    if "pipeline" not in st.session_state:
        st.session_state["pipeline"] = Pipeline(settings, audit)
    return st.session_state["pipeline"]


@st.cache_resource
def _live_check_times() -> list[float]:
    """When live checks ran on this server, shared by every visitor (for the hourly cap)."""
    return []


def live_check_blocked() -> str | None:
    """On the public demo, why another live check isn't allowed right now (None when it is)."""
    if not settings.public_site:
        return None
    if st.session_state.get("live_checks", 0) >= settings.live_checks_per_visitor:
        return (f"You've used your {settings.live_checks_per_visitor} live checks on this public demo. "
                "Turn on Replay recorded runs in the sidebar to see recorded results for every case.")
    times = _live_check_times()
    times[:] = [t for t in times if time.time() - t < 3600]
    if len(times) >= settings.live_checks_per_hour:
        return ("The public demo has reached its live-check limit for this hour, which protects the team's shared "
                "AMD quota. Turn on Replay recorded runs in the sidebar to see recorded results.")
    return None


def count_live_check() -> None:
    st.session_state["live_checks"] = st.session_state.get("live_checks", 0) + 1
    _live_check_times().append(time.time())


@st.cache_data(ttl=120, show_spinner=False)
def cached_health(base_url: str, model: str) -> dict:
    # keyed on URL/model so a changed endpoint is re-checked; cached so a dead endpoint never slows every
    # click, and so the check doesn't eat into Token Factory's shared per-minute limit
    result = model_health(settings, timeout=6)
    if not result["ok"] and "isn't in the Token Factory catalog" not in result.get("detail", ""):
        result = model_health(settings, timeout=12)  # one slow answer (a cold start) shouldn't read as down
    return result


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
    return f'<span class="lp-pill lp-{cls}">{icon(cls, 14)}<span>{label}</span></span>'


def page_header(title: str, sub: str) -> None:
    st.markdown(f'<header class="lp-page"><h1>{E(title)}</h1><p>{E(sub)}</p></header>', unsafe_allow_html=True)


def empty_state(ic: str, title: str, text: str) -> str:
    return f'<div class="lp-empty"><div class="ic">{icon(ic, 22)}</div><b>{E(title)}</b>{text}</div>'


def go(page: str) -> None:
    st.session_state["nav"] = page


CHAT_STARTERS = ("Hi! Who are you and what do you do?", "What is a three-way match?",
                 "What does invoice fraud usually look like?", "How do I verify a bank-account change safely?")


def ask_starter(question: str) -> None:
    st.session_state["chat_pending"] = question
    st.session_state["nav"] = "chat"


# ------------------------------------------------------------------ samples and links
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
    st.session_state["nav"] = "check"


options = sample_options()
by_case = {f.name: name for name, f in options.items()}
# ?case=case_07 checks that sample once when the page opens (before the navigation is drawn)
if not st.session_state.get("url_case_done") and st.query_params.get("case") in by_case:
    st.session_state["url_case_done"] = True
    queue_case(by_case[st.query_params["case"]])


# ------------------------------------------------------------------ sidebar
model_problem = settings.model_problem()
health = cached_health(settings.amd_base_url, settings.amd_model) if not model_problem else None
missing = settings.missing()
pending_count = len(audit.pending_review())

PAGES = {"overview": ":material/space_dashboard: Overview", "check": ":material/fact_check: Check an invoice",
         "chat": ":material/forum: Ask the agent", "queue": ":material/inbox: Review queue", "audit": ":material/history: Audit log",
         "results": ":material/insights: Results", "settings": ":material/tune: Settings"}

with st.sidebar:
    st.markdown(f'<div class="lp-brand"><div class="logo">{LOGO}</div><div><b>LedgerPilot</b>'
                '<span>Accounts payable</span></div></div>', unsafe_allow_html=True)
    page = st.radio("Navigation", list(PAGES), key="nav", label_visibility="collapsed",
                    format_func=lambda p: PAGES[p] + (f" ({pending_count})" if p == "queue" else ""))
    st.divider()
    recorded_cases = recording.available(settings.recordings_dir)
    # ?demo=1 opens the app in demo mode (a link to hand judges if the live services are down)
    demo_mode = st.toggle("Replay recorded runs", key="demo_mode",
                          value=st.query_params.get("demo") == "1",
                          help="Shows saved outputs of earlier live runs, clearly labelled as recorded. "
                               "Use it if the live services are slow or down.")
    st.caption(f"Demo mode · {len(recorded_cases)} recorded case(s) available." if recorded_cases else
               "Demo mode · no recordings yet. `python eval/run_eval.py` saves one per case.")
    st.divider()

    # Connections: one compact row each; the setup details sit in an expander so they never dominate the page
    if health and health["ok"]:
        where = "AMD Token Factory" if settings.token_factory else "AMD Developer Cloud"
        model_row = ("on", "Online", f'{E(str(health["weights"]))} served on {where} · {health["latency_ms"]} ms')
    elif health:
        model_row = ("off", "Unreachable", f"{E(settings.model_where)} endpoint not reachable")
    else:
        model_row = ("warn", "Not set up", "AMD model endpoint not set up")
    evolus_row = (("warn", "Not connected", f"{len(missing)} setting{'s' if len(missing) != 1 else ''} missing")
                  if missing else ("on", "Connected", "Agent, extractors" + (", workflow" if settings.workflow_id else "")
                                   + (", library" if settings.library_id else "")))
    st.markdown('<div class="lp-side-h">Connections</div><div class="lp-conn">'
                + "".join(f'<div class="row"><span class="lp-dot {s}"></span><div><b>{name}<em class="{s}">{state}</em></b>'
                          f'<small>{detail}</small></div></div>'
                          for name, (s, state, detail) in (("AMD model", model_row), ("Evolus", evolus_row)))
                + "</div>", unsafe_allow_html=True)
    if model_problem or missing or (health and not health["ok"]):
        with st.expander("How to connect", icon=":material/help:"):
            if model_problem:
                st.warning(f"AMD model endpoint isn't set up. {model_problem}")
            elif health and not health["ok"]:
                st.error(f"AMD model endpoint not reachable. {health['detail']}")
            if missing:
                st.warning("Evolus isn't connected. Missing in .env: " + ", ".join(missing))
    st.markdown('<p class="lp-side-foot">Checks run in Python. Reading, reasoning and actions run on Evolus, '
                + ("with the agent's model on AMD Token Factory." if settings.token_factory else
                   "with the agent's model served by vLLM on an AMD Instinct MI300X.")
                + " Every payment still needs a person's approval.</p>", unsafe_allow_html=True)

# A toast queued by the previous run (a finished check, a review, a cleared history)
if toast := st.session_state.pop("toast", None):
    st.toast(toast[0], icon=toast[1])

if demo_mode:
    st.markdown(f'<div class="lp-banner">{icon("history", 18)}<div><b>Demo mode.</b> Results are replays of recorded '
                'live runs, not live calls to Evolus or the AMD model. Turn it off in the sidebar to check invoices live.'
                '</div></div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ overview
def kpi(key: str, label: str, value: str, sub: str, tone: str, ic: str) -> str:
    return (f'<div class="lp-kpi tone-{tone}"><div class="top"><span class="k">{label}</span>'
            f'<span class="badge">{icon(ic, 18)}</span></div>'
            f'<div class="v" data-kpi="{key}">{value}</div><div class="s">{sub}</div></div>')


def decisions_chart(rows: list[dict]):
    """How many invoices ended in each decision: real counts from the audit log."""
    order = [r for r in TONE if any(x["final_route"] == r for x in rows)]
    d = pd.DataFrame([{"Decision": STAMP[r][0], "Invoices": sum(1 for x in rows if x["final_route"] == r)} for r in order])
    colours = [PALETTE[TONE[r]] for r in order]
    bars = alt.Chart(d).mark_bar(cornerRadiusEnd=5, height=22).encode(
        y=alt.Y("Decision:N", sort=[STAMP[r][0] for r in order], title=None,
                axis=alt.Axis(labelColor=PALETTE["ink-2"], labelFontSize=13, domain=False, ticks=False, labelPadding=8)),
        x=alt.X("Invoices:Q", title=None, axis=alt.Axis(tickMinStep=1, format="d", gridColor=PALETTE["line"], domain=False,
                                                       ticks=False, labelColor=PALETTE["muted"])),
        color=alt.Color("Decision:N", scale=alt.Scale(domain=[STAMP[r][0] for r in order], range=colours), legend=None),
        tooltip=["Decision", "Invoices"])
    text = bars.mark_text(align="left", dx=6, color=PALETTE["ink"], fontWeight=600).encode(text="Invoices:Q")
    return (bars + text).properties(height=max(120, 46 * len(order)), background="transparent").configure_view(
        strokeWidth=0).configure(font="Inter")


rows_all = audit.all(limit=10_000)
checked = len(rows_all)
held_rows = [r for r in rows_all if r["final_route"] == "hold_for_review"]
held = sum(Decimal(r["money_at_risk"] or 0) for r in held_rows)
blocked = sum(1 for r in rows_all if r["final_route"] == "escalate_fraud")
ready = sum(1 for r in rows_all if r["final_route"] == "approve_for_payment")


def supplier_of(row: dict) -> str:
    try:
        inv = (json.loads(row["extracted"] or "{}") or {}).get("invoice") or {}
    except ValueError:
        inv = {}
    return str(inv.get("supplier_name") or row["supplier_id"] or "Unknown supplier")


if page == "overview":
    head, ask, action = st.columns([1.5, .65, .75], vertical_alignment="center")
    with head:
        page_header("Accounts payable overview", "Every invoice checked before payment.")
    ask.button("Ask the agent", icon=":material/forum:", on_click=go, args=("chat",), width="stretch", key="go-chat")
    action.button("Check an invoice", type="primary", icon=":material/add:", on_click=go, args=("check",),
                  width="stretch", key="go-check")
    st.markdown('<section class="lp-kpis">'
                + kpi("checked", "Invoices checked", str(checked), "since history was cleared", "info", "file-check")
                + kpi("ready", "Ready to pay", str(ready), "waiting for a person's approval", "ok", "ok")
                + kpi("review", "Needs review", str(len(held_rows)), f"{money(held)} held from payment", "hold", "hold")
                + kpi("blocked", "Payments blocked", str(blocked), "possible fraud, supplier to verify", "fraud", "fraud")
                + "</section>", unsafe_allow_html=True)

    with st.container(key="card-agent"):
        agent_on = not missing
        st.markdown(f'<div class="lp-agent-head"><div class="ic">{icon("bot", 22)}</div><div>'
                    f'<div class="lp-section">Detective Clerk, your AI agent'
                    f'<span class="lp-pill lp-{"ok" if agent_on else "hold"}">{"Online" if agent_on else "Not connected"}'
                    f'</span></div><p class="lp-section-sub">Ask about invoices, three-way matching or supplier fraud. '
                    f'It runs on Evolus with {E(settings.amd_model or "the model")} on {E(settings.model_where)}, '
                    f'and explains every decision LedgerPilot makes.</p></div></div>', unsafe_allow_html=True)
        cols = st.columns(2)
        for i, q in enumerate(CHAT_STARTERS):
            cols[i % 2].button(q, key=f"ov-starter-{i}", on_click=ask_starter, args=(q,), width="stretch",
                           disabled=not agent_on)

    left, right = st.columns([1.15, 1], gap="medium")
    with left, st.container(key="card-activity"):
        st.markdown('<div class="lp-section">Review activity</div><p class="lp-section-sub">Decisions across every '
                    'invoice checked so far.</p>', unsafe_allow_html=True)
        if rows_all:
            st.altair_chart(decisions_chart(rows_all), width="stretch")
            stopped = sum(Decimal(str(r["money_at_risk"] or 0)) for r in rows_all
                          if r["final_route"] in ("hold_for_review", "escalate_fraud"))
            st.markdown(f'<p class="lp-small">Money held or blocked before payment: '
                        f'<b class="lp-num" style="color:var(--ink)">{money(stopped)}</b> · '
                        f'{pending_count} invoice{"s" if pending_count != 1 else ""} waiting in the review queue.</p>',
                        unsafe_allow_html=True)
        else:
            st.markdown(empty_state("file-check", "No invoices checked yet",
                                    "Run one of the scenarios on the Check an invoice page. Decisions appear here."),
                        unsafe_allow_html=True)
    with right, st.container(key="card-recent"):
        st.markdown('<div class="lp-section">Recent decisions</div><p class="lp-section-sub">The latest checks, '
                    'newest first.</p>', unsafe_allow_html=True)
        if rows_all:
            items = "".join(
                f'<li><div style="min-width:0"><div class="inv lp-num">{E(str(r["invoice_number"] or r["label"]))}</div>'
                f'<div class="sup">{E(supplier_of(r))}</div></div><div class="r">{chip(r["final_route"])}'
                f'<span class="amt">{money(r["total"])} {E(str(r["currency"] or ""))}</span></div></li>'
                for r in rows_all[:6])
            st.markdown(f'<ul class="lp-list">{items}</ul>', unsafe_allow_html=True)
        else:
            st.markdown(empty_state("inbox", "Nothing here yet", "Each checked invoice is listed with its supplier, "
                                    "decision and amount."), unsafe_allow_html=True)

    with st.container(key="card-how"):
        st.markdown('<div class="lp-section">How LedgerPilot decides</div><p class="lp-section-sub">Code does every '
                    'number. The agent explains and can only make a decision stricter, never looser.</p>',
                    unsafe_allow_html=True)
        steps = (("Read the PO, delivery note and invoice", "Evolus document extractors"),
                 ("Validate every field", "Python (Pydantic)"),
                 ("Three-way match and fraud checks", "Python, Decimal maths"),
                 ("Explain and route the case", f"Evolus agent on {settings.model_where}"),
                 ("Draft the email, start the workflow", "Evolus AI Tool and workflow"),
                 ("A person approves or rejects", "Review queue and audit log"))
        st.markdown('<ol class="lp-flow">' + "".join(f"<li><b>{E(a)}</b><span>{E(b)}</span></li>" for a, b in steps)
                    + "</ol>", unsafe_allow_html=True)


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
    mark = "background-color: #FDECEE; color: #C0303F; font-weight: 600"

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


def trail_html(res: CaseResult) -> str:
    rows = []
    for s in res.steps:
        mark = '<span class="okm" aria-label="succeeded">✓</span>' if s["ok"] else '<span class="bad" aria-label="failed">✗</span>'
        note = f'<div class="lp-small">{E(s["note"])}</div>' if s.get("note") else ""
        rows.append(f'<tr><td>{mark}</td><td>{E(s["step"])}{note}</td><td>{E(s["where"])}</td>'
                    f'<td class="t">{s["seconds"]:.2f} s</td></tr>')
    return f'<table class="lp-trail">{"".join(rows)}</table>' if rows else ""


def show_result(res: CaseResult, recorded: dict | None = None) -> None:
    route = res.route.value
    label, cls, sentence = STAMP[route]
    if recorded:
        st.markdown(f'<div class="lp-banner" style="margin-top:1.4rem">{icon("history", 18)}<div><b>Recorded run</b> · '
                    f'{E(str(recorded.get("case")))} recorded {E(str(recorded.get("at")))} with '
                    f'{E(str(recorded.get("model") or "unknown model"))} ({E(str(recorded.get("source") or ""))}). '
                    'This is a replay, not a live call.</div></div>', unsafe_allow_html=True)
    conf = ""
    if not res.error:
        if res.confidence_reasons:
            conf = (f'<p class="lp-conf lp-conf-low">Low confidence, handed to a human reviewer: '
                    f'{E("; ".join(res.confidence_reasons))}.</p>')
        else:
            conf = ('<p class="lp-conf">High confidence: every value was read and the agent agrees with '
                    'the checks.</p>')
    n = len(res.discrepancies)
    st.markdown(
        f'<section class="lp-decision {cls}"><div><div class="lp-eyebrow">Decision</div>'
        f'<div class="lp-stamp-row">{icon(cls, 26)}{stamp_html(route)}</div>'
        f'<p class="lp-verdict">{E(sentence)}</p>{conf}</div>'
        f'<div class="lp-vright"><div class="lp-eyebrow">Money at risk</div>'
        f'<div class="lp-figure">{money(res.money_at_risk)}</div>'
        f'<div class="lp-meta">{n} finding{"s" if n != 1 else ""} · decided in {res.timings.get("total_s", 0):.1f} s</div></div>'
        f'<div class="lp-next"><div>{icon("arrow-right", 18)}<span><b>Recommended next step</b>{E(NEXT_STEP[route])}</span></div>'
        f'<div class="human">{icon("user-check", 18)}<span><b>A person decides the payment</b>LedgerPilot never pays or '
        'approves anything itself. Every invoice waits in the review queue for a person.</span></div></div>'
        '</section>', unsafe_allow_html=True)

    if res.error:
        st.error(res.error)
        if res.steps:
            with st.expander("What ran, where" + (" (when recorded)" if recorded else ""), expanded=True):
                st.markdown(trail_html(res), unsafe_allow_html=True)
        return

    inv = res.extracted.get("invoice") or {}
    st.markdown('<div class="lp-doc">'
                f'<span>Invoice<b class="lp-num">{E(str(inv.get("invoice_number")))}</b></span>'
                f'<span>Supplier<b>{E(str(inv.get("supplier_name") or inv.get("supplier_id")))}</b></span>'
                f'<span>Purchase order<b class="lp-num">{E(str(inv.get("po_number")))}</b></span>'
                f'<span>Total due<b class="lp-num">{money(inv.get("total"))} {E(str(inv.get("currency") or ""))}</b></span>'
                '</div>', unsafe_allow_html=True)

    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.markdown("##### What the checks found")
        if res.discrepancies:
            st.markdown("".join(finding_html(d) for d in res.discrepancies), unsafe_allow_html=True)
            st.caption("Every figure here is calculated by code, not by the language model.")
        else:
            st.markdown('<div class="lp-clear"><p>Nothing to flag. Quantities, prices, totals, supplier and bank account '
                        f'all check out.</p><p class="lp-small">Checks that ran and passed: {E(", ".join(CHECKS_RUN))}.</p></div>',
                        unsafe_allow_html=True)
    with right:
        st.markdown("##### The agent's note")
        if res.agent:
            evidence = "".join(f"<li>{E(e)}</li>" for e in res.agent.evidence)
            st.markdown(f'<blockquote class="lp-quote"><div class="who">{icon("bot", 15)}Detective Clerk · Evolus agent</div>'
                        f'<p>{E(res.agent.explanation)}</p>{"<ul>" + evidence + "</ul>" if evidence else ""}</blockquote>',
                        unsafe_allow_html=True)
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
            st.text_area("Draft email", res.email_draft, height=190, label_visibility="collapsed")
            st.download_button("Download draft", res.email_draft, f"{inv.get('invoice_number') or 'invoice'}_draft.txt",
                               mime="text/plain", key="dl-draft", type="tertiary", icon=":material/download:")

    st.markdown("##### Order, delivery and invoice side by side")
    df = match_table(res)
    if df.empty:
        st.info("No invoice lines could be read.")
    else:
        st.dataframe(style_match(df), hide_index=True, width="stretch")
        st.caption("Highlighted cells differ from the purchase order or the delivery note.")
    with st.expander("Fields read from the documents", icon=":material/description:"):
        st.dataframe(fields_table(res), hide_index=True, width="stretch")
        st.caption("Read by the Evolus document extractors. The bank account is masked on screen.")
    with st.expander("What ran, where" + (" (when recorded)" if recorded else ""), icon=":material/route:"):
        st.markdown(trail_html(res), unsafe_allow_html=True)


def replay(case: str) -> bool:
    rec = recording.load(settings.recordings_dir, case)
    if rec is None:
        return False
    st.session_state.update(result=rec[0], result_meta=rec[1], result_case=case)
    return True


# ------------------------------------------------------------------ check an invoice
if page == "check":
    page_header("Check an invoice", "Pick a rehearsed scenario, or bring your own purchase order, delivery note and "
                "invoice. LedgerPilot runs every check and shows the evidence.")
    rehearsal = [r for r in REHEARSAL if r[0] in by_case]
    if rehearsal:
        current = st.session_state.get("sample_pick")
        cols = st.columns(len(rehearsal), gap="medium")
        for col, (case, title, expected, desc) in zip(cols, rehearsal, strict=True):
            tone = TONE[expected]
            selected = current == by_case[case] and st.session_state.get("doc_mode", "Use a sample case") == "Use a sample case"
            with col, st.container(key=f"scard-{tone}-{case}{'-sel' if selected else ''}"):
                st.markdown(f'<div class="lp-scn-head">{icon(tone, 20)}<b>{E(title)}</b></div>'
                            f'<p class="lp-scn-desc">{E(desc)}</p>'
                            f'<div class="lp-scn-exp">Expected: {chip(expected)}'
                            + ('<span class="lp-scn-sel">✓ Selected</span>' if selected else "") + '</div>',
                            unsafe_allow_html=True)
                st.button("Run check", key=f"scn-{case}", on_click=queue_case, args=(by_case[case],),
                          icon=":material/play_arrow:", width="stretch", help=f"{case.replace('_', ' ').capitalize()}: "
                          "loads the three documents and runs the full check in one click")

    with st.container(key="card-docs"):
        st.markdown('<div class="lp-section">Documents</div><p class="lp-section-sub">LedgerPilot needs all three: what was '
                    'ordered, what arrived, and what the supplier billed.</p>', unsafe_allow_html=True)
        st.session_state.setdefault("doc_mode", "Use a sample case")
        sources = ["Use a sample case"] if settings.public_site else ["Use a sample case", "Upload my own"]
        if st.session_state.get("doc_mode") not in sources:
            st.session_state["doc_mode"] = "Use a sample case"
        mode = st.segmented_control("Source", sources, key="doc_mode",
                                    label_visibility="collapsed") or "Use a sample case"
        if settings.public_site:
            left = max(settings.live_checks_per_visitor - st.session_state.get("live_checks", 0), 0)
            st.caption(f"Public demo: live checks use the 24 synthetic sample cases only, {left} of "
                       f"{settings.live_checks_per_visitor} left for you. Run the app locally to check your own documents.")
        docs, label = None, ""
        if mode == "Use a sample case":
            if not options:
                st.warning("No sample cases found. Run `python scripts/make_samples.py` first.")
            else:
                pick = st.selectbox("Sample case", list(options), key="sample_pick",
                                    help="24 synthetic cases: clean invoices, billing errors, fraud attempts and an unreadable PDF.")
                folder = options[pick]
                st.markdown('<p class="lp-small" style="margin:.2rem 0 .1rem">Source documents (PDF)</p>', unsafe_allow_html=True)
                c1, c2, c3 = st.columns(3)
                for col, (kind, name) in zip((c1, c2, c3), (("po", "Purchase order"), ("grn", "Delivery note"),
                                                            ("invoice", "Invoice")), strict=True):
                    col.download_button(name, (folder / f"{kind}.pdf").read_bytes(), f"{folder.name}_{kind}.pdf",
                                        mime="application/pdf", key=f"dl-{kind}", icon=":material/description:",
                                        width="stretch", help=f"Download the {name.lower()} PDF")
                docs, label = load_case_folder(folder), folder.name
        else:
            c1, c2, c3 = st.columns(3, gap="medium")
            kinds = ["pdf", "png", "jpg", "jpeg"]
            up_po = c1.file_uploader("Purchase order", type=kinds, help="What was ordered, at what price.")
            up_grn = c2.file_uploader("Delivery note (goods received)", type=kinds, help="What actually arrived.")
            up_inv = c3.file_uploader("Supplier invoice", type=kinds, help="What the supplier is asking to be paid.")
            got = sum(bool(u) for u in (up_po, up_grn, up_inv))
            if up_po and up_grn and up_inv:
                docs = {"po": (up_po.name, up_po.getvalue()), "grn": (up_grn.name, up_grn.getvalue()),
                        "invoice": (up_inv.name, up_inv.getvalue())}
                label = up_inv.name
            st.caption(f"{got} of 3 documents added. PDF, PNG or JPG, up to 20 MB each. Use synthetic documents only: "
                       "the shared AMD key must not see real supplier data.")
        clicked = st.button("Replay recorded result" if demo_mode else "Run invoice check", type="primary",
                            key="check-btn", disabled=docs is None, icon=":material/play_circle:",
                            help=None if docs is not None else "Add all three documents first.")

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
        if blocked_msg := live_check_blocked():
            st.session_state["notice"] = blocked_msg
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
        count_live_check()
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
            if st.button("Save for demo mode", key="save-rec", type="tertiary", icon=":material/bookmark_add:",
                         help="Stores this live result so demo mode can replay it, labelled as recorded."):
                try:
                    recording.save(settings.recordings_dir, res, case,
                                   model=(health or {}).get("weights") or settings.amd_model, source="app, live check")
                    st.success(f"Saved. Demo mode will replay this run of {case}.")
                except OSError as exc:
                    st.error(f"Couldn't save the recording ({type(exc).__name__}). Check RECORDINGS_DIR is writable.")
    else:
        with st.container(key="card-empty-result"):
            st.markdown(empty_state("file-check", "Nothing checked yet", "Run a scenario above, or choose documents and "
                                    "press Run invoice check. The decision and its evidence appear here."),
                        unsafe_allow_html=True)


# ------------------------------------------------------------------ ask the agent
if page == "chat":
    page_header("Ask the agent", "Chat with Detective Clerk, the Evolus agent behind LedgerPilot. Ask how a three-way "
                "match works, what invoice fraud looks like, or how to verify a supplier safely.")
    history: list[dict[str, str]] = st.session_state.setdefault("chat", [])
    if settings.missing():
        with st.container(key="card-chat-off"):
            st.markdown(empty_state("bot", "The agent isn't connected here", "This deployment has no Evolus settings. "
                                    "Run LedgerPilot with its .env, or open the agent in the Evolus portal."),
                        unsafe_allow_html=True)
    else:
        if not history:
            with st.container(key="card-chat-start"):
                st.markdown('<div class="lp-section">Try asking</div><p class="lp-section-sub">Answers come from the '
                            f'agent on {E(settings.amd_model or "the model")} ({E(settings.model_where)}) through Evolus, '
                            'using the vendor master and the AP fraud guide in its knowledge library.</p>',
                            unsafe_allow_html=True)
                cols = st.columns(2)
                for i, q in enumerate(CHAT_STARTERS):
                    cols[i % 2].button(q, key=f"starter-{i}", on_click=ask_starter, args=(q,), width="stretch")
        for m in history:
            with st.chat_message(m["role"], avatar=":material/person:" if m["role"] == "user" else ":material/smart_toy:"):
                st.markdown(m["content"])
        question = st.chat_input("Ask Detective Clerk about invoices, fraud or how LedgerPilot works")
        question = question or st.session_state.pop("chat_pending", None)
        if question:
            used = sum(1 for m in history if m["role"] == "user")
            if settings.public_site and used >= settings.chat_messages_per_visitor:
                st.info(f"You've used your {settings.chat_messages_per_visitor} questions on this public demo.")
            else:
                history.append({"role": "user", "content": question[:2000]})
                with st.chat_message("user", avatar=":material/person:"):
                    st.markdown(history[-1]["content"])
                with st.chat_message("assistant", avatar=":material/smart_toy:"), st.spinner("Detective Clerk is thinking"):
                    try:
                        answer = mask_accounts(ClerkAgent(settings).chat(history[-10:]))
                        answer = re.sub(r"\)Skip\.?", ".", answer)  # a stray token this model sometimes emits
                    except Exception as exc:  # noqa: BLE001 - a clerk sees a sentence, never a stack trace
                        answer = f"The agent didn't answer this time ({type(exc).__name__}). Please try again in a moment."
                history.append({"role": "assistant", "content": answer or "The agent sent an empty reply. Please try again."})
                st.rerun()
        if history:
            st.button("Start a new conversation", key="chat-reset", type="tertiary", icon=":material/refresh:",
                      on_click=lambda: st.session_state.update(chat=[]))
        st.caption("The agent explains and teaches; it never approves or releases a payment. Answers can be wrong, so "
                   "check anything important against your own records.")


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


if page == "queue":
    pending = audit.pending_review()
    page_header("Review queue", "Nothing is paid until a person releases it. A blocked payment needs a note saying how "
                "the supplier was verified.")
    note_missing = st.session_state.pop("note_missing", None)
    if not pending:
        with st.container(key="card-queue-empty"):
            st.markdown(empty_state("inbox", "The queue is clear", "Every checked invoice lands here, and nothing is "
                                    "paid until a person releases it."), unsafe_allow_html=True)
    else:
        st.markdown(f'<p class="lp-section-sub"><b style="color:var(--ink)">{len(pending)} invoice'
                    f'{"s" if len(pending) != 1 else ""} waiting</b> · newest first. Release only what you have checked.</p>',
                    unsafe_allow_html=True)
    for row in pending:
        with st.container(key=f"q-{row['final_route']}-{row['id']}"):
            info, act = st.columns([2.4, 1], gap="large")
            info.markdown(f'<div class="lp-qhead"><b class="lp-num">{E(str(row["invoice_number"] or row["label"]))}</b>'
                          f'{chip(row["final_route"])}</div>'
                          f'<div class="lp-qmeta">{E(supplier_of(row))} · '
                          f'total <span class="lp-num">{money(row["total"])} {E(str(row["currency"] or ""))}</span> · '
                          f'at risk <span class="lp-num">{money(row["money_at_risk"])}</span> · '
                          f'checked {E(str(row["created_at"] or "")[:16].replace("T", " "))} UTC</div>',
                          unsafe_allow_html=True)
            if row["explanation"]:
                info.markdown(f'<div class="lp-qnote">{E(row["explanation"])}</div>', unsafe_allow_html=True)
            if row["error"]:
                info.markdown(f'<div class="lp-qitem">{E(row["error"])}</div>', unsafe_allow_html=True)
            for d in json.loads(row["discrepancies"] or "[]"):
                info.markdown(f'<div class="lp-qitem"><b>{E(FINDING.get(d["code"], d["code"]))}</b>: {E(d["message"])}</div>',
                              unsafe_allow_html=True)
            blocked_row = row["final_route"] == "escalate_fraud"
            act.text_input("Reviewer note", key=f"note{row['id']}",
                           placeholder="Required to release a blocked payment" if blocked_row else "Optional note")
            if row["final_route"] == "processing_error":
                # An invoice that could not be read can never be released from here.
                act.caption("Can't be paid from here. Check the documents by hand or upload readable copies.")
            else:
                act.button("Release for payment", key=f"release-{row['id']}", on_click=review_case, type="primary",
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
    c = PALETTE
    base = alt.Chart(d).encode(
        x=alt.X("check:Q", title="Check number", axis=alt.Axis(tickMinStep=1, format="d", grid=False, labelColor=c["muted"],
                                                              titleColor=c["muted"], domainColor=c["line"], tickColor=c["line"])),
        y=alt.Y("stopped:Q", title=None, axis=alt.Axis(gridColor=c["line"], domain=False, ticks=False,
                                                      labelColor=c["muted"], format=",.0f", tickCount=4)))
    area = base.mark_area(color=c["accent"], opacity=0.12, interpolate="step-after")
    line = base.mark_line(color=c["accent"], strokeWidth=2, interpolate="step-after")
    points = base.mark_circle(color=c["accent"], size=36).encode(
        tooltip=[alt.Tooltip("check:Q", title="Check"), alt.Tooltip("invoice_number:N", title="Invoice"),
                 alt.Tooltip("stopped:Q", title="Stopped so far", format=",.2f")])
    return ((area + line + points).properties(height=200, background="transparent")
            .configure_view(strokeWidth=0).configure(font="Inter"))


if page == "audit":
    page_header("Audit log", "Every check, its decision and the Evolus run IDs behind it.")
    rows = audit.all()
    if not rows:
        with st.container(key="card-audit-empty"):
            st.markdown(empty_state("history", "No history yet", "Every check is recorded here with its decision and "
                                    "Evolus run IDs."), unsafe_allow_html=True)
    else:
        df = pd.DataFrame(rows)
        df["Decision"] = df["final_route"].map(lambda r: STAMP.get(r, (r,))[0])
        stopped_total = sum(Decimal(str(r["money_at_risk"] or 0)) for r in rows
                            if r["final_route"] in ("hold_for_review", "escalate_fraud"))
        chart_col, mix_col = st.columns([1.6, 1], gap="medium")
        with chart_col, st.container(key="card-exposure"):
            st.markdown(f'<div class="lp-section">Money stopped before payment</div><p class="lp-section-sub">'
                        f'<b class="lp-num" style="color:var(--ink)">{money(stopped_total)}</b> held or blocked across '
                        f'{len(rows)} check{"s" if len(rows) != 1 else ""}, accumulated in the order they ran.</p>',
                        unsafe_allow_html=True)
            if len(rows) > 1:
                st.altair_chart(exposure_chart(df), width="stretch")
        with mix_col, st.container(key="card-mix"):
            st.markdown('<div class="lp-section">Decision mix</div><p class="lp-section-sub">Share of every invoice '
                        'checked.</p>', unsafe_allow_html=True)
            st.altair_chart(decisions_chart(rows), width="stretch")
        with st.container(key="card-log"):
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
                               type="tertiary", icon=":material/download:")


# ------------------------------------------------------------------ results
if page == "results":
    page_header("Results", "Measured on the 24 synthetic cases with the live services: accuracy, fraud caught and speed.")
    with st.container(key="card-results"):
        shown = False
        for name in ("evaluation.md", "benchmark.md"):
            path = ROOT / "docs" / name
            if path.exists():
                st.markdown(path.read_text(encoding="utf-8"))
                shown = True
        if not shown:
            st.markdown(empty_state("file-check", "No measured results yet", 'Run <code>python eval/run_eval.py</code> and '
                                    '<code>python scripts/benchmark_amd.py</code> once the AMD endpoint and Evolus are '
                                    'connected; the tables appear here.'), unsafe_allow_html=True)


# ------------------------------------------------------------------ settings
if page == "settings":
    page_header("Settings", "Connection status, model checks and demo data. Keys stay in the server's .env and are "
                "never shown here.")
    left, right = st.columns(2, gap="medium")
    with left, st.container(key="card-model"):
        st.markdown('<div class="lp-section">AMD model</div>', unsafe_allow_html=True)
        if health and health["ok"]:
            st.markdown(f'<p class="lp-section-sub"><b>Model:</b> {E(str(health["weights"]))} served on '
                        f'{"AMD Token Factory" if settings.token_factory else "AMD Developer Cloud"} · endpoint answered in '
                        f'{health["latency_ms"]} ms</p>', unsafe_allow_html=True)
            if st.button("Measure model speed", width="stretch", icon=":material/speed:",
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
                if st.button("Check team usage", width="stretch", icon=":material/data_usage:",
                             help="Asks Token Factory how much of the daily quota your team's shared key has left."):
                    st.session_state["usage"] = model_usage(settings)
                usage = st.session_state.get("usage")
                if usage and usage["ok"]:
                    with st.expander("Token Factory usage (shared by your team)"):
                        st.json(usage["usage"])
                elif usage:
                    st.caption(f"Usage check failed: {usage['detail']}")
        elif health:
            st.error(f"AMD model endpoint not reachable. {health['detail']}")
        else:
            st.warning(f"AMD model endpoint isn't set up. {model_problem}")
        if settings.token_factory:
            st.caption(f"[AMD Token Factory]({TOKEN_FACTORY_SIGN_IN}): one free key per team, shared limits. "
                       "Send only the synthetic sample invoices.")
    with right, st.container(key="card-evolus"):
        st.markdown('<div class="lp-section">Evolus workspace</div><p class="lp-section-sub">Which pieces are configured. '
                    'Values are never displayed.</p>', unsafe_allow_html=True)
        pieces = (("API key", settings.evolus_api_key), ("Workspace (app) ID", settings.evolus_app_id),
                  ("Agent", settings.evolus_agent_id), ("Invoice extractor", settings.extractor_invoice_id),
                  ("Purchase order extractor", settings.extractor_po_id), ("Delivery note extractor", settings.extractor_grn_id),
                  ("Exception routing workflow (optional)", settings.workflow_id),
                  ("Vendor library (optional)", settings.library_id))
        st.markdown("".join(f'<div class="lp-kv"><span>{name}</span><em class="{"on" if value else "off"}">'
                            f'{"✓ Set" if value else "Not set"}</em></div>' for name, value in pieces), unsafe_allow_html=True)
    with st.container(key="card-demo"):
        st.markdown('<div class="lp-section">Demo data</div><p class="lp-section-sub">Clearing the history empties the '
                    'audit log and review queue, so sample invoices can be checked again without being flagged as '
                    'duplicates.</p>', unsafe_allow_html=True)
        if st.button("Clear demo history", icon=":material/restart_alt:",
                     help="Empties the audit log so sample invoices can be checked again without being flagged as duplicates."):
            audit.reset()
            st.session_state.pop("result", None)
            st.session_state["toast"] = ("Demo history cleared. Sample invoices can be checked again.", ":material/restart_alt:")
            st.rerun()
