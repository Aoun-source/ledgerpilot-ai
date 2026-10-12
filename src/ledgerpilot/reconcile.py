"""Three-way match: purchase order vs goods-received note vs invoice.

Pure Python, Decimal arithmetic, no model calls. Every finding is a Discrepancy
with the expected value, the actual value and the money at risk, so a finance
clerk can verify it in seconds.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .schemas import Discrepancy, GoodsReceipt, Invoice, PurchaseOrder, Route

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _s(v: object) -> Optional[str]:
    return None if v is None else str(v)


def _d(code: str, field: str, expected: object, actual: object, message: str,
       impact: Optional[Decimal] = None, route: Route = Route.HOLD) -> Discrepancy:
    return Discrepancy(code=code, route=route, field=field, expected=_s(expected),
                       actual=_s(actual), impact=impact, message=message)


def _norm(text: Optional[str]) -> str:
    return (text or "").strip().upper()


REQUIRED_INVOICE_FIELDS = ("invoice_number", "invoice_date", "po_number", "supplier_id", "currency", "total")


def three_way_match(po: PurchaseOrder, grn: GoodsReceipt, inv: Invoice,
                    price_tolerance: Decimal = ZERO,
                    total_tolerance: Decimal = CENT) -> list[Discrepancy]:
    issues: list[Discrepancy] = []

    # 1. Required fields: missing data is never guessed, it goes to a person.
    for name in REQUIRED_INVOICE_FIELDS:
        if getattr(inv, name) in (None, ""):
            issues.append(_d("MISSING_FIELD", f"invoice.{name}", "present", None,
                             f"Invoice field '{name}' could not be read; a person must check it."))
    if not inv.lines:
        issues.append(_d("MISSING_FIELD", "invoice.lines", "at least one line", "none",
                         "No line items could be read from the invoice."))

    # 2. Header consistency across the three documents.
    if inv.po_number and po.po_number and _norm(inv.po_number) != _norm(po.po_number):
        issues.append(_d("PO_MISMATCH", "po_number", po.po_number, inv.po_number,
                         "Invoice refers to a different purchase order."))
    if grn.po_number and po.po_number and _norm(grn.po_number) != _norm(po.po_number):
        issues.append(_d("GRN_PO_MISMATCH", "grn.po_number", po.po_number, grn.po_number,
                         "Goods-received note belongs to a different purchase order."))
    if inv.supplier_id and po.supplier_id and _norm(inv.supplier_id) != _norm(po.supplier_id):
        issues.append(_d("SUPPLIER_MISMATCH", "supplier_id", po.supplier_id, inv.supplier_id,
                         "Invoice supplier differs from the purchase order supplier."))
    if inv.currency and po.currency and _norm(inv.currency) != _norm(po.currency):
        issues.append(_d("CURRENCY_MISMATCH", "currency", po.currency, inv.currency,
                         "Invoice currency differs from the purchase order."))

    # 3. Line-level checks.
    po_lines = {_norm(l.sku): l for l in po.lines if l.sku}
    received: dict[str, Decimal] = {}
    for l in grn.lines:
        if l.sku and l.qty_received is not None:
            received[_norm(l.sku)] = received.get(_norm(l.sku), ZERO) + l.qty_received

    computed_subtotal = ZERO
    subtotal_known = True
    for i, line in enumerate(inv.lines, start=1):
        key = _norm(line.sku)
        label = line.sku or f"line {i}"
        if line.qty is None or line.unit_price is None:
            issues.append(_d("MISSING_FIELD", f"line {label}", "qty and unit price", None,
                             f"Quantity or unit price unreadable on {label}."))
            subtotal_known = False
            continue

        if line.line_total is not None and (line.qty * line.unit_price - line.line_total).copy_abs() > total_tolerance:
            issues.append(_d("LINE_ARITHMETIC", f"line {label}", line.qty * line.unit_price, line.line_total,
                             f"{label}: {line.qty} x {line.unit_price} does not equal the line total.",
                             impact=(line.line_total - line.qty * line.unit_price).copy_abs()))
        computed_subtotal += line.line_total if line.line_total is not None else line.qty * line.unit_price

        p = po_lines.get(key)
        if p is None:
            issues.append(_d("ITEM_NOT_ON_PO", f"line {label}", "item on PO", label,
                             f"{label} is billed but not on the purchase order.",
                             impact=line.qty * line.unit_price))
            continue

        if p.unit_price is not None and (line.unit_price - p.unit_price).copy_abs() > price_tolerance:
            diff = (line.unit_price - p.unit_price) * line.qty
            issues.append(_d("PRICE_VARIANCE", f"line {label}", p.unit_price, line.unit_price,
                             f"{label}: billed {line.unit_price} per unit, PO agreed {p.unit_price}; "
                             f"difference {diff.quantize(CENT)} on {line.qty} units.",
                             impact=diff.quantize(CENT)))

        if p.qty is not None and line.qty > p.qty:
            over = line.qty - p.qty
            issues.append(_d("QTY_OVER_PO", f"line {label}", p.qty, line.qty,
                             f"{label}: billed {line.qty}, ordered only {p.qty}.",
                             impact=(over * line.unit_price).quantize(CENT)))

        got = received.get(key, ZERO)
        if line.qty > got:
            short = line.qty - got
            issues.append(_d("QTY_NOT_RECEIVED", f"line {label}", got, line.qty,
                             f"{label}: billed {line.qty}, goods-received note shows {got}.",
                             impact=(short * line.unit_price).quantize(CENT)))

    # 4. Totals arithmetic.
    if subtotal_known and inv.lines:
        if inv.subtotal is not None and (computed_subtotal - inv.subtotal).copy_abs() > total_tolerance:
            issues.append(_d("SUBTOTAL_ARITHMETIC", "subtotal", computed_subtotal, inv.subtotal,
                             "Line totals do not add up to the stated subtotal.",
                             impact=(inv.subtotal - computed_subtotal).copy_abs()))
        base = inv.subtotal if inv.subtotal is not None else computed_subtotal
        if inv.total is not None and (base + (inv.tax or ZERO) - inv.total).copy_abs() > total_tolerance:
            issues.append(_d("TOTAL_ARITHMETIC", "total", base + (inv.tax or ZERO), inv.total,
                             "Subtotal plus tax does not equal the invoice total.",
                             impact=(inv.total - base - (inv.tax or ZERO)).copy_abs()))

    return issues
