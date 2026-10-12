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

REQUIRED_INVOICE_FIELDS = ("invoice_number", "invoice_date", "po_number", "supplier_id", "currency", "total")


def _s(v: object) -> Optional[str]:
    return None if v is None else str(v)


def _issue(code: str, field: str, expected: object, actual: object, message: str,
           impact: Optional[Decimal] = None, route: Route = Route.HOLD) -> Discrepancy:
    return Discrepancy(code=code, route=route, field=field, expected=_s(expected),
                       actual=_s(actual), impact=impact, message=message)


def _norm(text: Optional[str]) -> str:
    return (text or "").strip().upper()


def _money(x: Decimal) -> Decimal:
    return x.quantize(CENT)


def three_way_match(po: PurchaseOrder, grn: GoodsReceipt, inv: Invoice,
                    price_tolerance: Decimal = ZERO,
                    total_tolerance: Decimal = CENT) -> list[Discrepancy]:
    issues: list[Discrepancy] = []

    # 1. Required fields: missing data is never guessed, it goes to a person.
    for name in REQUIRED_INVOICE_FIELDS:
        if getattr(inv, name) in (None, ""):
            issues.append(_issue("MISSING_FIELD", f"invoice.{name}", "present", None,
                                 f"Invoice field '{name}' could not be read; a person must check it."))
    if not inv.lines:
        issues.append(_issue("MISSING_FIELD", "invoice.lines", "at least one line", "none",
                             "No line items could be read from the invoice."))

    # 2. Header consistency across the three documents.
    if inv.po_number and po.po_number and _norm(inv.po_number) != _norm(po.po_number):
        issues.append(_issue("PO_MISMATCH", "po_number", po.po_number, inv.po_number,
                             "Invoice refers to a different purchase order."))
    if grn.po_number and po.po_number and _norm(grn.po_number) != _norm(po.po_number):
        issues.append(_issue("GRN_PO_MISMATCH", "grn.po_number", po.po_number, grn.po_number,
                             "Goods-received note belongs to a different purchase order."))
    if inv.supplier_id and po.supplier_id and _norm(inv.supplier_id) != _norm(po.supplier_id):
        issues.append(_issue("SUPPLIER_MISMATCH", "supplier_id", po.supplier_id, inv.supplier_id,
                             "Invoice supplier differs from the purchase order supplier."))
    if grn.supplier_id and po.supplier_id and _norm(grn.supplier_id) != _norm(po.supplier_id):
        issues.append(_issue("GRN_SUPPLIER_MISMATCH", "grn.supplier_id", po.supplier_id, grn.supplier_id,
                             "Goods were received from a different supplier than the purchase order."))
    if inv.currency and po.currency and _norm(inv.currency) != _norm(po.currency):
        issues.append(_issue("CURRENCY_MISMATCH", "currency", po.currency, inv.currency,
                             "Invoice currency differs from the purchase order."))

    # 3. Index the PO and the GRN by SKU (a SKU may appear on several lines).
    po_qty: dict[str, Decimal] = {}
    po_price: dict[str, Optional[Decimal]] = {}
    for pl in po.lines:
        if not pl.sku:
            continue
        key = _norm(pl.sku)
        po_qty[key] = po_qty.get(key, ZERO) + (pl.qty or ZERO)
        po_price.setdefault(key, pl.unit_price)
    received: dict[str, Decimal] = {}
    for gl in grn.lines:
        if gl.sku and gl.qty_received is not None:
            received[_norm(gl.sku)] = received.get(_norm(gl.sku), ZERO) + gl.qty_received

    # 4. Line-level checks: arithmetic, item on PO, agreed price.
    computed_subtotal = ZERO
    subtotal_known = True
    billed_qty: dict[str, Decimal] = {}
    billed_price: dict[str, Decimal] = {}
    labels: dict[str, str] = {}
    for i, line in enumerate(inv.lines, start=1):
        key = _norm(line.sku)
        label = line.sku or f"line {i}"
        if line.qty is None or line.unit_price is None:
            issues.append(_issue("MISSING_FIELD", f"line {label}", "qty and unit price", None,
                                 f"Quantity or unit price unreadable on {label}."))
            subtotal_known = False
            continue

        expected_total = line.qty * line.unit_price
        if line.line_total is not None and (expected_total - line.line_total).copy_abs() > total_tolerance:
            issues.append(_issue("LINE_ARITHMETIC", f"line {label}", _money(expected_total), line.line_total,
                                 f"{label}: {line.qty} x {line.unit_price} does not equal the line total.",
                                 impact=_money((line.line_total - expected_total).copy_abs())))
        computed_subtotal += line.line_total if line.line_total is not None else expected_total

        if not key or key not in po_qty:
            issues.append(_issue("ITEM_NOT_ON_PO", f"line {label}", "item on PO", label,
                                 f"{label} is billed but not on the purchase order.",
                                 impact=_money(expected_total)))
            continue

        agreed = po_price.get(key)
        if agreed is not None and (line.unit_price - agreed).copy_abs() > price_tolerance:
            diff = _money((line.unit_price - agreed) * line.qty)
            issues.append(_issue("PRICE_VARIANCE", f"line {label}", agreed, line.unit_price,
                                 f"{label}: billed {line.unit_price} per unit, PO agreed {agreed}; "
                                 f"difference {diff} on {line.qty} units.", impact=diff))

        billed_qty[key] = billed_qty.get(key, ZERO) + line.qty
        billed_price.setdefault(key, line.unit_price)
        labels.setdefault(key, label)

    # 5. Quantity checks per item, across all invoice lines for that item.
    for key, qty in billed_qty.items():
        label, price = labels[key], billed_price[key]
        if qty > po_qty[key]:
            issues.append(_issue("QTY_OVER_PO", f"line {label}", po_qty[key], qty,
                                 f"{label}: billed {qty}, ordered only {po_qty[key]}.",
                                 impact=_money((qty - po_qty[key]) * price)))
        got = received.get(key, ZERO)
        if qty > got:
            issues.append(_issue("QTY_NOT_RECEIVED", f"line {label}", got, qty,
                                 f"{label}: billed {qty}, goods-received note shows {got}.",
                                 impact=_money((qty - got) * price)))

    # 6. Totals arithmetic.
    if subtotal_known and inv.lines:
        if inv.subtotal is not None and (computed_subtotal - inv.subtotal).copy_abs() > total_tolerance:
            issues.append(_issue("SUBTOTAL_ARITHMETIC", "subtotal", _money(computed_subtotal), inv.subtotal,
                                 "Line totals do not add up to the stated subtotal.",
                                 impact=_money((inv.subtotal - computed_subtotal).copy_abs())))
        base = inv.subtotal if inv.subtotal is not None else computed_subtotal
        tax = inv.tax or ZERO
        if inv.total is not None and (base + tax - inv.total).copy_abs() > total_tolerance:
            issues.append(_issue("TOTAL_ARITHMETIC", "total", _money(base + tax), inv.total,
                                 "Subtotal plus tax does not equal the invoice total.",
                                 impact=_money((inv.total - base - tax).copy_abs())))

    return issues
