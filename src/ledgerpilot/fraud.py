"""Vendor fraud guard: unknown suppliers, changed bank details, duplicate invoices.

Any finding here escalates the case as possible fraud. These are never
auto-approved, whatever the model says.
"""
from __future__ import annotations

import csv
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Optional

from .schemas import Discrepancy, Invoice, PastInvoice, Route, Vendor

DUPLICATE_WINDOW_DAYS = 30


def load_vendor_master(path: str | Path) -> dict[str, Vendor]:
    with open(path, newline="", encoding="utf-8") as fh:
        return {row["supplier_id"].strip().upper(): Vendor(**row) for row in csv.DictReader(fh)}


def _mask(iban: Optional[str]) -> Optional[str]:
    """Show only the last 4 characters of a bank account in evidence."""
    if not iban:
        return iban
    return "*" * max(len(iban) - 4, 0) + iban[-4:]


def fraud_checks(inv: Invoice, vendors: dict[str, Vendor],
                 history: Iterable[PastInvoice] = ()) -> list[Discrepancy]:
    issues: list[Discrepancy] = []
    sid = (inv.supplier_id or "").strip().upper()
    vendor = vendors.get(sid)

    if sid and vendor is None:
        issues.append(Discrepancy(code="UNKNOWN_VENDOR", route=Route.FRAUD, field="supplier_id",
                                  expected="supplier in vendor master", actual=inv.supplier_id,
                                  impact=inv.total,
                                  message="Supplier is not in the vendor master file."))

    if vendor is not None:
        if not inv.bank_iban:
            issues.append(Discrepancy(code="BANK_MISSING", route=Route.HOLD, field="bank_iban",
                                      expected=_mask(vendor.iban), actual=None,
                                      message="No bank account could be read from the invoice."))
        elif inv.bank_iban != vendor.iban:
            issues.append(Discrepancy(code="BANK_MISMATCH", route=Route.FRAUD, field="bank_iban",
                                      expected=_mask(vendor.iban), actual=_mask(inv.bank_iban),
                                      impact=inv.total,
                                      message=(f"Invoice asks for payment to a bank account that differs from "
                                               f"the vendor master for {vendor.name}. Verify by phone using a "
                                               f"known contact, never the number on the invoice.")))

    for past in history:
        if (past.supplier_id or "").strip().upper() != sid or not sid:
            continue
        same_number = (past.invoice_number and inv.invoice_number
                       and past.invoice_number.strip().upper() == inv.invoice_number.strip().upper())
        if same_number:
            issues.append(Discrepancy(code="DUPLICATE_INVOICE", route=Route.FRAUD, field="invoice_number",
                                      expected="new invoice number", actual=inv.invoice_number,
                                      impact=inv.total,
                                      message=f"Invoice {inv.invoice_number} from this supplier was already processed."))
            break
        close_in_time = (past.invoice_date and inv.invoice_date
                         and abs(inv.invoice_date - past.invoice_date) <= timedelta(days=DUPLICATE_WINDOW_DAYS))
        if close_in_time and past.total is not None and inv.total is not None and past.total == inv.total:
            issues.append(Discrepancy(code="POSSIBLE_DUPLICATE", route=Route.FRAUD, field="total",
                                      expected=f"no earlier invoice for {past.total} within {DUPLICATE_WINDOW_DAYS} days",
                                      actual=f"{past.invoice_number} on {past.invoice_date}",
                                      impact=inv.total,
                                      message=(f"Same supplier billed the same amount ({inv.total}) on "
                                               f"{past.invoice_date} under number {past.invoice_number}.")))
            break
    return issues


def total_impact(issues: Iterable[Discrepancy]) -> Decimal:
    return sum((i.impact for i in issues if i.impact is not None), Decimal("0"))
