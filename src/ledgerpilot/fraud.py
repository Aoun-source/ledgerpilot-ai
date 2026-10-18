"""Vendor fraud guard: unknown suppliers, changed bank details, duplicate invoices.

Fraud findings escalate the case. They are never auto-approved, whatever the
model says.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from collections.abc import Iterable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .schemas import Discrepancy, Invoice, PastInvoice, Route, Vendor

DUPLICATE_WINDOW_DAYS = 30


def load_vendor_master(path: str | Path) -> dict[str, Vendor]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return {row["supplier_id"].strip().upper(): Vendor(**row) for row in csv.DictReader(fh)}


def mask(iban: Optional[str]) -> Optional[str]:
    """Show only the last 4 characters of a bank account in evidence and logs."""
    if not iban:
        return iban
    return "*" * max(len(iban) - 4, 0) + iban[-4:]


_ACCOUNT = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){10,30}\b")


def mask_accounts(text: str) -> str:
    """Mask anything shaped like an IBAN in free text, keeping the last 4 characters."""
    return _ACCOUNT.sub(lambda m: mask(m.group(0).replace(" ", "")), text or "")


def _norm(text: Optional[str]) -> str:
    return (text or "").strip().upper()


_LOOKALIKE = str.maketrans("OIL", "011")


def invoice_key(number: Optional[str]) -> str:
    """Fingerprint of an invoice number that survives cosmetic edits.

    AC-7710, ac 7710, AC/07710, AC-771O (letter O) and AC-7710-A all give AC7710,
    so a paid invoice can't be sent again with a slightly different number.
    """
    text = unicodedata.normalize("NFKC", number or "").upper()   # full-width and other odd forms -> plain
    text = re.sub(r"[^A-Z0-9]", "", text)                        # drop spaces, dashes, slashes, dots
    text = text.translate(_LOOKALIKE)                            # letters that look like digits
    text = re.sub(r"(?<=\d)[A-Z]{1,3}$", "", text)               # trailing letters: 7710A, 7710REV
    return re.sub(r"(?<!\d)0+(?=\d)", "", text)                  # leading zeros: 07710 -> 7710


def fraud_checks(inv: Invoice, vendors: dict[str, Vendor], history: Iterable[PastInvoice] = (),
                 fallback_supplier_id: Optional[str] = None) -> list[Discrepancy]:
    issues: list[Discrepancy] = []
    # If the invoice shows no supplier ID, check against the PO's supplier rather than skip the checks.
    supplier_id = inv.supplier_id or fallback_supplier_id
    sid = _norm(supplier_id)
    vendor = vendors.get(sid) if sid else None

    if sid and vendor is None:
        issues.append(Discrepancy(code="UNKNOWN_VENDOR", route=Route.FRAUD, field="supplier_id",
                                  expected="supplier in vendor master", actual=supplier_id,
                                  impact=inv.total,
                                  message="Supplier is not in the vendor master file."))

    if vendor is not None:
        if inv.currency and _norm(inv.currency) != _norm(vendor.currency):
            issues.append(Discrepancy(code="CURRENCY_MISMATCH", route=Route.HOLD, field="vendor.currency",
                                      expected=vendor.currency, actual=inv.currency,
                                      message=(f"Invoice is in {inv.currency}, but the vendor master lists "
                                               f"{vendor.currency} for {vendor.name}.")))
        if not inv.bank_iban:
            issues.append(Discrepancy(code="BANK_MISSING", route=Route.HOLD, field="bank_iban",
                                      expected=mask(vendor.iban), actual=None,
                                      message="No bank account could be read from the invoice."))
        elif inv.bank_iban != vendor.iban:
            issues.append(Discrepancy(code="BANK_MISMATCH", route=Route.FRAUD, field="bank_iban",
                                      expected=mask(vendor.iban), actual=mask(inv.bank_iban),
                                      impact=inv.total,
                                      message=(f"Invoice asks for payment to a bank account that differs from "
                                               f"the vendor master for {vendor.name}. Verify by phone using a "
                                               f"known contact, never the number on the invoice.")))

    if not sid:
        return issues
    same_supplier = [p for p in history if _norm(p.supplier_id) == sid]

    # Exact duplicate: same supplier, same invoice number.
    number = _norm(inv.invoice_number)
    if number and any(_norm(p.invoice_number) == number for p in same_supplier):
        issues.append(Discrepancy(code="DUPLICATE_INVOICE", route=Route.FRAUD, field="invoice_number",
                                  expected="new invoice number", actual=inv.invoice_number,
                                  impact=inv.total,
                                  message=f"Invoice {inv.invoice_number} from this supplier was already processed."))
        return issues

    # Look-alike duplicate: same supplier, a number that differs only cosmetically.
    key = invoice_key(inv.invoice_number)
    twin = next((p for p in same_supplier if key and invoice_key(p.invoice_number) == key), None)
    if twin is not None:
        issues.append(Discrepancy(
            code="LOOKALIKE_INVOICE_NUMBER", route=Route.FRAUD, field="invoice_number",
            expected="new invoice number", actual=inv.invoice_number, impact=inv.total,
            message=(f"Invoice number {inv.invoice_number} looks like {twin.invoice_number}, which was already "
                     f"processed for this supplier. They differ only in punctuation, spacing, leading zeros, "
                     f"look-alike characters or a trailing letter.")))
        return issues

    # Near duplicate: same supplier, same total, within the window, different number.
    if inv.total is not None and inv.invoice_date is not None:
        for past in same_supplier:
            if (past.total == inv.total and past.invoice_date is not None
                    and abs(inv.invoice_date - past.invoice_date) <= timedelta(days=DUPLICATE_WINDOW_DAYS)):
                issues.append(Discrepancy(
                    code="POSSIBLE_DUPLICATE", route=Route.FRAUD, field="total",
                    expected=f"no earlier invoice for {past.total} within {DUPLICATE_WINDOW_DAYS} days",
                    actual=f"{past.invoice_number} on {past.invoice_date}", impact=inv.total,
                    message=(f"Same supplier billed the same amount ({inv.total}) on {past.invoice_date} "
                             f"under number {past.invoice_number}.")))
                break
    return issues


QTY_CODES = {"QTY_OVER_PO", "QTY_NOT_RECEIVED", "PO_ALREADY_BILLED"}


def total_impact(issues: Iterable[Discrepancy], cap: Optional[Decimal] = None) -> Decimal:
    """Money at risk without double counting: a fraud finding puts the whole invoice
    at risk, so it caps the figure; otherwise the line-level impacts add up.

    Only overcharges count (an undercharge must not hide one), extra units flagged by
    more than one quantity check count once, and the sum never exceeds `cap`
    (the invoice total)."""
    issues = list(issues)
    fraud = [i.impact for i in issues if i.route is Route.FRAUD and i.impact is not None]
    if fraud:
        return max(fraud)
    total = Decimal("0")
    qty_by_line: dict[str, Decimal] = {}
    for i in issues:
        if i.impact is None or i.impact <= 0:
            continue
        if i.code in QTY_CODES:
            qty_by_line[i.field] = max(qty_by_line.get(i.field, Decimal("0")), i.impact)
        else:
            total += i.impact
    total += sum(qty_by_line.values(), Decimal("0"))
    return min(total, cap) if cap is not None and cap > 0 else total
