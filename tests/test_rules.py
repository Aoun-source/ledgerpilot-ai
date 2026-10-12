"""Rules-engine tests. No network, no model: these run anywhere in seconds."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from ledgerpilot.fraud import fraud_checks, load_vendor_master
from ledgerpilot.reconcile import three_way_match
from ledgerpilot.rules import evaluate, final_route
from ledgerpilot.schemas import GoodsReceipt, Invoice, PastInvoice, PurchaseOrder, Route

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
VENDORS = load_vendor_master(ROOT / "data" / "vendor_master.csv")
HISTORY = [PastInvoice(**h) for h in json.loads((ROOT / "data" / "history.json").read_text())]
CASES = sorted(p for p in SAMPLES.glob("case_*/truth.json"))


def load(path: Path):
    t = json.loads(path.read_text())
    inv = Invoice(**t["invoice"]) if t["invoice"] else None
    return t, PurchaseOrder(**t["po"]), GoodsReceipt(**t["grn"]), inv


def test_dataset_present():
    assert len(CASES) == 20, "run: python scripts/make_samples.py"


@pytest.mark.parametrize("truth_path", CASES, ids=lambda p: p.parent.name)
def test_every_case_routes_as_expected(truth_path):
    truth, po, grn, inv = load(truth_path)
    if inv is None:
        pytest.skip("corrupt-PDF case is handled by the pipeline, not the rules engine")
    decision = evaluate(po, grn, inv, VENDORS, HISTORY)
    assert decision.route.value == truth["expected_route"], [d.message for d in decision.discrepancies]
    assert sorted({d.code for d in decision.discrepancies}) == sorted(truth["expected_codes"])


def test_price_variance_is_exactly_200_dollars():
    _, po, grn, inv = load(SAMPLES / "case_07" / "truth.json")
    issues = three_way_match(po, grn, inv)
    assert len(issues) == 1
    assert issues[0].impact == Decimal("200.00")
    assert issues[0].expected == "20.00" and issues[0].actual == "22.00"


def test_short_delivery_impact():
    _, po, grn, inv = load(SAMPLES / "case_09" / "truth.json")
    (issue,) = three_way_match(po, grn, inv)
    assert issue.code == "QTY_NOT_RECEIVED"
    assert issue.impact == Decimal("142.50")  # 10 missing x 14.25


def test_bank_change_is_fraud_and_masked():
    _, _, _, inv = load(SAMPLES / "case_15" / "truth.json")
    (issue,) = fraud_checks(inv, VENDORS, HISTORY)
    assert issue.route is Route.FRAUD
    assert issue.actual.endswith("3215") and issue.actual.startswith("*")  # never show full account


def test_missing_fields_go_to_a_person():
    _, po, grn, inv = load(SAMPLES / "case_01" / "truth.json")
    broken = inv.model_copy(update={"invoice_number": None, "total": None})
    issues = three_way_match(po, grn, broken)
    assert {i.field for i in issues if i.code == "MISSING_FIELD"} == {"invoice.invoice_number", "invoice.total"}
    assert all(i.route is Route.HOLD for i in issues)


def test_money_parsing_handles_symbols_and_commas():
    inv = Invoice(total="$1,250.50", tax="€ 0", lines=[{"qty": "2", "unit_price": "1,000.00"}])
    assert inv.total == Decimal("1250.50") and inv.lines[0].unit_price == Decimal("1000.00")


def test_garbage_number_is_rejected():
    with pytest.raises(ValueError):
        Invoice(total="twelve hundred")


@pytest.mark.parametrize("rule,agent,expected", [
    (Route.APPROVE, Route.HOLD, Route.HOLD),           # agent may be stricter
    (Route.FRAUD, Route.APPROVE, Route.FRAUD),         # agent can never loosen
    (Route.HOLD, None, Route.HOLD),                    # agent unavailable -> rules decide
])
def test_agent_can_only_raise_the_route(rule, agent, expected):
    assert final_route(rule, agent) is expected
