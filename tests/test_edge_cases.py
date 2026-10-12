"""Edge cases found in the QA review, one test per bug fixed."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ledgerpilot.audit import AuditLog
from ledgerpilot.config import ConfigError, Settings
from ledgerpilot.fraud import fraud_checks, total_impact
from ledgerpilot.reconcile import three_way_match
from ledgerpilot.schemas import (
    Discrepancy,
    GoodsReceipt,
    Invoice,
    PastInvoice,
    PurchaseOrder,
    Route,
    Vendor,
    to_date,
    to_decimal,
)

D = Decimal


# ------------------------------------------------------------- number parsing
@pytest.mark.parametrize("raw,expected", [
    ("1,250.50", "1250.50"), ("1.250,50", "1250.50"), ("22,5", "22.5"), ("22,50", "22.50"),
    ("1,250", "1250"), ("1,250,000", "1250000"), ("1.250.000", "1250000"), ("$22", "22"),
    ("€ 0", "0"), ("100 pcs", "100"), ("(200.00)", "-200.00"), ("-15", "-15"), (7, "7"),
    (2.5, "2.5"), ("PKR 3,400", "3400"),
])
def test_to_decimal(raw, expected):
    assert to_decimal(raw) == D(expected)


@pytest.mark.parametrize("raw", ["twelve hundred", "n/a", True])
def test_to_decimal_rejects_non_numbers(raw):
    with pytest.raises(ValueError):
        to_decimal(raw)


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-05", date(2026, 10, 5)), ("05/10/2026", date(2026, 10, 5)), ("5.10.2026", date(2026, 10, 5)),
    ("5 Oct 2026", date(2026, 10, 5)), ("October 5, 2026", date(2026, 10, 5)), ("5th Oct 2026", date(2026, 10, 5)),
    ("2026-10-05T10:00:00Z", date(2026, 10, 5)), ("10/25/2026", date(2026, 10, 25)), ("someday", None), ("", None),
])
def test_to_date(raw, expected):
    assert to_date(raw) == expected


def test_numeric_ids_null_lines_and_currency_symbols():
    inv = Invoice(invoice_number=88123, po_number=4501, supplier_id=1, lines=None, currency="€", invoice_date="05/10/2026")
    assert inv.invoice_number == "88123" and inv.po_number == "4501" and inv.supplier_id == "1"
    assert inv.lines == [] and inv.currency == "EUR" and inv.invoice_date == date(2026, 10, 5)


def test_unreadable_date_becomes_missing_field_hold():
    po = PurchaseOrder(po_number="P1", supplier_id="V1", currency="USD", lines=[{"sku": "A", "qty": 1, "unit_price": 5}])
    grn = GoodsReceipt(po_number="P1", lines=[{"sku": "A", "qty_received": 1}])
    inv = Invoice(invoice_number="I1", invoice_date="someday", po_number="P1", supplier_id="V1", currency="USD",
                  lines=[{"sku": "A", "qty": 1, "unit_price": 5, "line_total": 5}], subtotal=5, tax=0, total=5)
    issues = three_way_match(po, grn, inv)
    assert [i.field for i in issues] == ["invoice.invoice_date"] and issues[0].route is Route.HOLD


def test_iban_with_spaces_and_dashes_matches_vendor_master():
    vendors = {"V1": Vendor(supplier_id="V1", name="X", iban="GB82 ACME 0000 1234", currency="USD")}
    inv = Invoice(supplier_id="v1", bank_iban="gb82-acme-0000-1234", invoice_number="I", total=1)
    assert fraud_checks(inv, vendors) == []


# ------------------------------------------------------------- reconciliation
def _docs(inv_lines, received=100, po_qty=100):
    po = PurchaseOrder(po_number="P1", supplier_id="V1", currency="USD", lines=[{"sku": "A", "qty": po_qty, "unit_price": 10}])
    grn = GoodsReceipt(po_number="P1", supplier_id="V1", lines=[{"sku": "A", "qty_received": received}])
    sub = sum(D(q) * 10 for q in inv_lines)
    inv = Invoice(invoice_number="I1", invoice_date="2026-10-05", po_number="P1", supplier_id="V1", currency="USD",
                  lines=[{"sku": "A", "qty": q, "unit_price": 10, "line_total": D(q) * 10} for q in inv_lines],
                  subtotal=sub, tax=0, total=sub)
    return po, grn, inv


def test_quantity_split_across_lines_is_caught():
    po, grn, inv = _docs([60, 60])  # 120 billed, 100 ordered and received
    codes = {i.code: i for i in three_way_match(po, grn, inv)}
    assert set(codes) == {"QTY_OVER_PO", "QTY_NOT_RECEIVED"}
    assert codes["QTY_NOT_RECEIVED"].impact == D("200.00")


def test_split_lines_within_limits_pass():
    po, grn, inv = _docs([50, 50])
    assert three_way_match(po, grn, inv) == []


def test_grn_from_other_supplier():
    po, grn, inv = _docs([100])
    grn = grn.model_copy(update={"supplier_id": "V9"})
    assert [i.code for i in three_way_match(po, grn, inv)] == ["GRN_SUPPLIER_MISMATCH"]


def test_line_without_sku_is_not_on_po():
    po, grn, inv = _docs([100])
    inv.lines[0].sku = None
    assert "ITEM_NOT_ON_PO" in {i.code for i in three_way_match(po, grn, inv)}


# ---------------------------------------------------------------- fraud
def test_exact_duplicate_found_even_if_near_duplicate_listed_first():
    vendors = {"V1": Vendor(supplier_id="V1", name="X", iban="IB1", currency="USD")}
    inv = Invoice(supplier_id="V1", bank_iban="IB1", invoice_number="N-2", invoice_date="2026-10-05", total=100)
    history = [PastInvoice(supplier_id="V1", invoice_number="N-1", invoice_date="2026-10-01", total=100),
               PastInvoice(supplier_id="V1", invoice_number="N-2", invoice_date="2026-09-01", total=90)]
    assert [i.code for i in fraud_checks(inv, vendors, history)] == ["DUPLICATE_INVOICE"]


def test_same_amount_outside_window_is_fine():
    vendors = {"V1": Vendor(supplier_id="V1", name="X", iban="IB1", currency="USD")}
    inv = Invoice(supplier_id="V1", bank_iban="IB1", invoice_number="N-2", invoice_date="2026-10-05", total=100)
    history = [PastInvoice(supplier_id="V1", invoice_number="N-1", invoice_date="2026-08-01", total=100)]
    assert fraud_checks(inv, vendors, history) == []


def test_money_at_risk_never_exceeds_invoice_on_fraud():
    issues = [Discrepancy(code="BANK_MISMATCH", route=Route.FRAUD, field="b", impact=D("1000"), message="m"),
              Discrepancy(code="PRICE_VARIANCE", route=Route.HOLD, field="p", impact=D("200"), message="m")]
    assert total_impact(issues) == D("1000")
    assert total_impact([issues[1], issues[1]]) == D("400")


# ---------------------------------------------------------------- audit + config
def test_failed_and_rejected_cases_are_not_payment_history(tmp_path):
    log = AuditLog(tmp_path / "a.db")
    base = {"supplier_id": "V1", "invoice_date": "2026-10-05", "total": "100"}
    log.record({**base, "invoice_number": "OK-1", "final_route": "hold_for_review"})
    log.record({**base, "invoice_number": "ERR-1", "final_route": "processing_error"})
    rej = log.record({**base, "invoice_number": "REJ-1", "final_route": "hold_for_review"})
    log.review(rej, "rejected_by_reviewer", "wrong price")
    assert [p.invoice_number for p in log.history()] == ["OK-1"]
    assert {r["invoice_number"] for r in log.pending_review()} == {"OK-1", "ERR-1"}


def test_empty_env_values_use_defaults(monkeypatch):
    monkeypatch.setenv("PRICE_TOLERANCE", "")
    monkeypatch.setenv("VLLM_MODEL", "  ")
    s = Settings()
    assert s.price_tolerance == D("0.00") and s.vllm_model == "ledgerpilot-model"


def test_bad_tolerance_is_a_clear_config_error(monkeypatch):
    monkeypatch.setenv("PRICE_TOLERANCE", "ten")
    with pytest.raises(ConfigError, match="PRICE_TOLERANCE"):
        Settings()


def test_placeholder_endpoint_detected(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "http://<DROPLET_IP>:8000/v1")
    assert Settings().placeholder_vllm()
