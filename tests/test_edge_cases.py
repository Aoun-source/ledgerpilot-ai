"""Edge cases found in the QA review, one test per bug fixed."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ledgerpilot.audit import AuditLog
from ledgerpilot.config import ConfigError, Settings
from ledgerpilot.fraud import fraud_checks, total_impact
from ledgerpilot.reconcile import three_way_match
from ledgerpilot.rules import evaluate
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


# ------------------------------------------- unreadable PO / GRN never approves
def test_unreadable_po_price_is_held_not_approved():
    po, grn, inv = _docs([100])
    po.lines[0].unit_price = None
    inv.lines[0].unit_price, inv.lines[0].line_total = D(99), D(9900)
    inv.subtotal = inv.total = D(9900)
    (issue,) = three_way_match(po, grn, inv)
    assert issue.code == "MISSING_FIELD" and issue.field == "po line A" and issue.route is Route.HOLD


@pytest.mark.parametrize("name", ["po_number", "supplier_id", "currency"])
def test_unreadable_po_header_is_held(name):
    po, grn, inv = _docs([100])
    setattr(po, name, None)
    assert [(i.code, i.field) for i in three_way_match(po, grn, inv)] == [("MISSING_FIELD", f"po.{name}")]


def test_grn_without_po_number_is_held():
    po, grn, inv = _docs([100])
    grn.po_number = None
    assert [(i.code, i.field) for i in three_way_match(po, grn, inv)] == [("MISSING_FIELD", "grn.po_number")]


# ------------------------------------------------- credit notes, negative values
def test_credit_note_is_never_approved_for_payment():
    po, grn, inv = _docs([-10])  # -10 units, total -100
    issues = three_way_match(po, grn, inv)
    assert {(i.code, i.field) for i in issues} == {("NEGATIVE_VALUE", "total"), ("NEGATIVE_VALUE", "line A")}
    assert all(i.route is Route.HOLD for i in issues)


def test_negative_unit_price_is_flagged():
    po, grn, inv = _docs([100])
    inv.lines[0].unit_price, inv.lines[0].line_total = D(-10), D(-1000)
    assert "NEGATIVE_VALUE" in {i.code for i in three_way_match(po, grn, inv)}


# ------------------------------------------------- same item twice on the PO
def test_item_on_po_at_two_prices_goes_to_a_person():
    po, grn, inv = _docs([100, 100], received=200)  # all 200 billed at 10
    po = PurchaseOrder(**{**po.model_dump(), "lines": [{"sku": "A", "qty": 100, "unit_price": 10},
                                                       {"sku": "A", "qty": 100, "unit_price": 8}]})
    (issue,) = three_way_match(po, grn, inv)       # reported once, not once per invoice line
    assert issue.code == "PO_PRICE_AMBIGUOUS" and issue.actual == "8, 10"


def test_item_on_two_po_lines_at_one_price_passes():
    po, grn, inv = _docs([100])
    po = PurchaseOrder(**{**po.model_dump(), "lines": [{"sku": "A", "qty": 50, "unit_price": 10}] * 2})
    assert three_way_match(po, grn, inv) == []


# ---------------------------------------------------------------- money at risk
def _price_issue(impact):
    return Discrepancy(code="PRICE_VARIANCE", route=Route.HOLD, field="p", impact=D(impact), message="m")


def test_undercharge_does_not_hide_an_overcharge():
    assert total_impact([_price_issue("200"), _price_issue("-200")]) == D("200")


def test_extra_units_are_counted_once():
    po, grn, inv = _docs([60, 60])  # 20 units too many: not ordered AND not received
    assert total_impact(three_way_match(po, grn, inv)) == D("200.00")


def test_money_at_risk_is_capped_at_the_invoice_total():
    assert total_impact([_price_issue("200"), _price_issue("200")], cap=D("300")) == D("300")
    assert total_impact([_price_issue("200")], cap=None) == D("200")


# ------------------------------------------------- invoice-number tricks
_V1 = {"V1": Vendor(supplier_id="V1", name="X", iban="IB1", currency="USD")}
_PAID = [PastInvoice(supplier_id="V1", invoice_number="AC-7710", invoice_date="2026-06-01", total=512)]


def _resubmit(number, supplier_id="V1"):
    inv = Invoice(supplier_id=supplier_id, bank_iban="IB1", currency="USD", invoice_number=number,
                  invoice_date="2026-10-05", total=999)
    return fraud_checks(inv, _V1, _PAID)


@pytest.mark.parametrize("number", ["AC7710", "ac 7710", "AC/7710", "AC-07710", "AC‑7710", "AC-7710.",
                                    "AC-7710-A", "AC-7710rev", "ＡＣ-7710", "AC-771O", "AC-77I0"])
def test_reformatted_invoice_number_is_still_a_duplicate(number):
    (issue,) = _resubmit(number)
    assert issue.code == "LOOKALIKE_INVOICE_NUMBER" and issue.route is Route.FRAUD
    assert "AC-7710" in issue.message and issue.impact == D(999)


def test_identical_invoice_number_keeps_the_exact_duplicate_code():
    assert [i.code for i in _resubmit("ac-7710 ")] == ["DUPLICATE_INVOICE"]


@pytest.mark.parametrize("number", ["AC-7711", "AC-77101", "AC-7710-2", "BC-7710"])
def test_genuinely_different_invoice_number_passes(number):
    assert _resubmit(number) == []


def test_lookalike_number_from_another_supplier_is_not_a_duplicate():
    vendors = {**_V1, "V2": Vendor(supplier_id="V2", name="Y", iban="IB1", currency="USD")}
    inv = Invoice(supplier_id="V2", bank_iban="IB1", currency="USD", invoice_number="AC7710",
                  invoice_date="2026-10-05", total=999)
    assert fraud_checks(inv, vendors, _PAID) == []


# ------------------------------------------------- vendor checks that used to be skipped
def test_missing_supplier_id_still_gets_the_bank_check():
    inv = Invoice(bank_iban="XX99EVIL", currency="USD", invoice_number="N-1", invoice_date="2026-10-05", total=100)
    assert fraud_checks(inv, _V1) == []  # nothing to look up without any supplier
    (issue,) = fraud_checks(inv, _V1, fallback_supplier_id="V1")
    assert issue.code == "BANK_MISMATCH" and issue.route is Route.FRAUD


def test_evaluate_uses_the_po_supplier_when_the_invoice_has_none():
    po, grn, inv = _docs([100])
    inv.supplier_id, inv.bank_iban = None, "XX99EVIL"
    decision = evaluate(po, grn, inv, _V1)
    assert decision.route is Route.FRAUD
    assert {d.code for d in decision.discrepancies} == {"MISSING_FIELD", "BANK_MISMATCH"}
    assert decision.money_at_risk == D(1000)


def test_invoice_currency_must_match_the_vendor_master():
    inv = Invoice(supplier_id="V1", bank_iban="IB1", currency="EUR", invoice_number="N-1", total=100)
    (issue,) = fraud_checks(inv, _V1)
    assert (issue.code, issue.field, issue.route) == ("CURRENCY_MISMATCH", "vendor.currency", Route.HOLD)
    assert (issue.expected, issue.actual) == ("USD", "EUR")


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
    monkeypatch.setenv("AMD_MODEL", "  ")
    s = Settings()
    assert s.price_tolerance == D("0.00") and s.amd_model == "DeepSeek-V4-Flash"


def test_token_factory_is_the_default_endpoint():
    s = Settings()
    assert s.token_factory and s.amd_base_url == "https://developer.amd.com.cn/radeon/api/v1"
    assert s.model_where == "AMD Token Factory"
    assert "AMD_API_KEY" in s.model_problem() and "notebooks.amd.com/tokenfactory" in s.model_problem()
    s.amd_api_key = "rc-" + "0" * 48
    assert s.model_problem() is None


def test_old_vllm_names_still_work(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "http://10.0.0.5:8000/v1")
    monkeypatch.setenv("VLLM_API_KEY", "vk")
    s = Settings()
    assert not s.token_factory and s.amd_api_key == "vk" and s.amd_model == "ledgerpilot-model"
    assert s.model_where == "AMD MI300X (vLLM)" and s.model_problem() is None
    monkeypatch.setenv("AMD_BASE_URL", "https://developer.amd.com.cn/radeon/api/v1")
    assert Settings().token_factory  # the new name wins


def test_bad_tolerance_is_a_clear_config_error(monkeypatch):
    monkeypatch.setenv("PRICE_TOLERANCE", "ten")
    with pytest.raises(ConfigError, match="PRICE_TOLERANCE"):
        Settings()


def test_placeholder_endpoint_detected(monkeypatch):
    monkeypatch.setenv("AMD_BASE_URL", "http://<DROPLET_IP>:8000/v1")
    s = Settings()
    assert s.placeholder_model() and "placeholder" in s.model_problem()
