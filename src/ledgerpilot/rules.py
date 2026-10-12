"""Combine the deterministic checks into one rule-based decision."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from .fraud import fraud_checks, total_impact
from .reconcile import three_way_match
from .schemas import (Discrepancy, GoodsReceipt, Invoice, PastInvoice, PurchaseOrder, Route,
                      Vendor, strictest)


@dataclass
class RuleDecision:
    route: Route
    discrepancies: list[Discrepancy] = field(default_factory=list)

    @property
    def money_at_risk(self) -> Decimal:
        return total_impact(self.discrepancies)


def evaluate(po: PurchaseOrder, grn: GoodsReceipt, inv: Invoice, vendors: dict[str, Vendor],
             history: Iterable[PastInvoice] = (), price_tolerance: Decimal = Decimal("0")) -> RuleDecision:
    issues = three_way_match(po, grn, inv, price_tolerance=price_tolerance)
    issues += fraud_checks(inv, vendors, history)
    return RuleDecision(route=strictest([i.route for i in issues]), discrepancies=issues)


def final_route(rule_route: Route, agent_route: Route | None) -> Route:
    """The agent may make a case stricter, never looser than the rules allow."""
    if agent_route is None:
        return rule_route
    return strictest([rule_route, agent_route])
