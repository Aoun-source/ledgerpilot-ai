"""Three-way match: purchase order vs goods-received note vs invoice.

Pure Python, Decimal arithmetic, no model calls. Every finding is a Discrepancy
with the expected value, the actual value and the money at risk, so a finance
clerk can verify it in seconds.
"""
from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Optional

from .fraud import invoice_key
from .schemas import Discrepancy, GoodsReceipt, Invoice, PastInvoice, PurchaseOrder, Route

ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_TAX_RATE = Decimal("0.30")  # default ceiling for tax as a share of the subtotal; set MAX_TAX_RATE to change

REQUIRED_INVOICE_FIELDS = ("invoice_number", "invoice_date", "po_number", "supplier_id", "currency", "total")
REQUIRED_PO_FIELDS = ("po_number", "supplier_id", "currency")


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
                    total_tolerance: Decimal = CENT,
                    max_tax_rate: Optional[Decimal] = MAX_TAX_RATE) -> list[Discrepancy]:
    issues: list[Discrepancy] = []

    # 1. Required fields: missing data is never guessed, it goes to a person.
    for name in REQUIRED_INVOICE_FIELDS:
        if getattr(inv, name) in (None, ""):
            issues.append(_issue("MISSING_FIELD", f"invoice.{name}", "present", None,
                                 f"Invoice field '{name}' could not be read; a person must check it."))
    if not inv.lines:
        issues.append(_issue("MISSING_FIELD", "invoice.lines", "at least one line", "none",
                             "No line items could be read from the invoice."))
    # The same goes for the PO and the GRN: a check that can't run must not count as a pass.
    for name in REQUIRED_PO_FIELDS:
        if getattr(po, name) in (None, ""):
            issues.append(_issue("MISSING_FIELD", f"po.{name}", "present", None,
                                 f"Purchase order field '{name}' could not be read; a person must check it."))
    if grn.po_number in (None, ""):
        issues.append(_issue("MISSING_FIELD", "grn.po_number", "present", None,
                             "Goods-received note does not show which purchase order it belongs to."))
    if inv.total is not None and inv.total < ZERO:
        issues.append(_issue("NEGATIVE_VALUE", "total", "a positive amount", inv.total,
                             "Invoice total is negative: this looks like a credit note, not an invoice to pay."))

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
    po_prices: dict[str, set[Optional[Decimal]]] = {}
    for pl in po.lines:
        if not pl.sku:
            continue
        key = _norm(pl.sku)
        po_qty[key] = po_qty.get(key, ZERO) + (pl.qty or ZERO)
        po_prices.setdefault(key, set()).add(pl.unit_price)
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
        if line.qty < ZERO or line.unit_price < ZERO:
            issues.append(_issue("NEGATIVE_VALUE", f"line {label}", "positive quantity and price",
                                 f"{line.qty} x {line.unit_price}",
                                 f"{label}: negative quantity or price. This looks like a credit or a reading "
                                 f"error; a person must check it."))

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

        # Compare prices only when the PO gives exactly one readable price for the item;
        # the other cases are reported once per item in step 5.
        if len(po_prices[key]) == 1 and None not in po_prices[key]:
            (agreed,) = po_prices[key]
            if (line.unit_price - agreed).copy_abs() > price_tolerance:
                diff = _money((line.unit_price - agreed) * line.qty)
                issues.append(_issue("PRICE_VARIANCE", f"line {label}", agreed, line.unit_price,
                                     f"{label}: billed {line.unit_price} per unit, PO agreed {agreed}; "
                                     f"difference {diff} on {line.qty} units.", impact=diff))

        billed_qty[key] = billed_qty.get(key, ZERO) + line.qty
        billed_price.setdefault(key, line.unit_price)
        labels.setdefault(key, label)

    # 5. Price source and quantity checks per item, across all invoice lines for that item.
    for key, qty in billed_qty.items():
        label, price = labels[key], billed_price[key]
        if None in po_prices[key]:
            issues.append(_issue("MISSING_FIELD", f"po line {label}", "agreed unit price", None,
                                 f"{label}: the agreed price on the purchase order could not be read, "
                                 f"so the billed price can't be checked."))
        elif len(po_prices[key]) > 1:
            listed = ", ".join(str(p) for p in sorted(po_prices[key]))
            issues.append(_issue("PO_PRICE_AMBIGUOUS", f"po line {label}", "one agreed price", listed,
                                 f"{label} is on the purchase order at more than one price ({listed}); "
                                 f"a person must check which applies."))
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

    # 7. Tax sanity. The PO carries no tax, so an inflated tax line is the easy way to pad an
    # invoice whose sums still add up.
    if inv.tax is not None and max_tax_rate is not None:
        tax_base = inv.subtotal if inv.subtotal is not None else (computed_subtotal if subtotal_known else None)
        if inv.tax < ZERO:
            issues.append(_issue("TAX_OUT_OF_RANGE", "tax", "zero or more", inv.tax, "Tax on the invoice is negative."))
        elif tax_base is not None and tax_base > ZERO and inv.tax > tax_base * max_tax_rate:
            rate = f"{(max_tax_rate * 100).normalize():f}%"
            limit = _money(tax_base * max_tax_rate)
            issues.append(_issue("TAX_OUT_OF_RANGE", "tax", f"at most {limit} ({rate} of {tax_base})", inv.tax,
                                 f"Tax of {inv.tax} is more than {rate} of the subtotal {tax_base}.",
                                 impact=_money(inv.tax - tax_base * max_tax_rate)))

    return issues


def po_balance(po: PurchaseOrder, inv: Invoice, history: Iterable[PastInvoice]) -> list[Discrepancy]:
    """Each ordered unit may be billed once. Add up what earlier invoices already billed
    on this purchase order and flag an invoice that goes past what was ordered."""
    po_no, sid, this = _norm(po.po_number), _norm(po.supplier_id), invoice_key(inv.invoice_number)
    if not po_no:
        return []
    already: dict[str, Decimal] = {}
    earlier: dict[str, str] = {}  # fingerprint -> number, so a resubmitted copy is counted once
    for past in history:
        key = invoice_key(past.invoice_number)
        if _norm(past.po_number) != po_no or _norm(past.supplier_id) != sid or key == this or key in earlier:
            continue
        earlier[key] = past.invoice_number or "an earlier invoice"
        for ln in past.lines:
            if ln.sku and ln.qty is not None:
                already[_norm(ln.sku)] = already.get(_norm(ln.sku), ZERO) + ln.qty
    if not already:
        return []

    ordered: dict[str, Decimal] = {}
    for pl in po.lines:
        if pl.sku:
            ordered[_norm(pl.sku)] = ordered.get(_norm(pl.sku), ZERO) + (pl.qty or ZERO)
    now: dict[str, Decimal] = {}
    price: dict[str, Decimal] = {}
    labels: dict[str, str] = {}
    for ln in inv.lines:
        key = _norm(ln.sku)
        if key in ordered and ln.qty is not None:
            now[key] = now.get(key, ZERO) + ln.qty
            price.setdefault(key, ln.unit_price or ZERO)
            labels.setdefault(key, ln.sku)

    names = ", ".join(list(earlier.values())[:3])
    issues: list[Discrepancy] = []
    for key, qty in now.items():
        before = already.get(key, ZERO)
        excess = min(qty, before + qty - ordered[key])
        if before > ZERO and excess > ZERO:
            left = max(ordered[key] - before, ZERO)
            issues.append(_issue("PO_ALREADY_BILLED", f"line {labels[key]}", f"at most {left} more", qty,
                                 f"{labels[key]}: {before} of {ordered[key]} ordered units were already billed "
                                 f"on {names}; this invoice bills {qty} more.",
                                 impact=_money(excess * price[key])))
    return issues
