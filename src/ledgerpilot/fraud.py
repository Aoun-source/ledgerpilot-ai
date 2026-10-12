"""Vendor fraud guard: unknown suppliers, changed bank details, duplicate invoices.

Fraud findings escalate the case. They are never auto-approved, whatever the
model says.
"""
from __future__ import annotations

import csv
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


def _norm(text: Optional[str]) -> str:
    return (text or "").strip().upper()


def fraud_checks(inv: Invoice, vendors: dict[str, Vendor],
                 history: Iterable[PastInvoice] = ()) -> list[Discrepancy]:
    issues: list[Discrepancy] = []
    sid = _norm(inv.supplier_id)
    vendor = vendors.get(sid) if sid else None

    if sid and vendor is None:
        issues.append(Discrepancy(code="UNKNOWN_VENDOR", route=Route.FRAUD, field="supplier_id",
                                  expected="supplier in vendor master", actual=inv.supplier_id,
                                  impact=inv.total,
                                  message="Supplier is not in the vendor master file."))

    if vendor is not None:
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


def total_impact(issues: Iterable[Discrepancy]) -> Decimal:
    """Money at risk without double counting: a fraud finding puts the whole invoice
    at risk, so it caps the figure; otherwise the line-level impacts add up."""
    issues = list(issues)
    fraud = [i.impact for i in issues if i.route is Route.FRAUD and i.impact is not None]
    if fraud:
        return max(fraud)
    return sum((i.impact for i in issues if i.impact is not None), Decimal("0"))
