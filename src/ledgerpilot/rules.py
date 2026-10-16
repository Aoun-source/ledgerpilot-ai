"""Combine the deterministic checks into one rule-based decision."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from .fraud import fraud_checks, total_impact
from .reconcile import MAX_TAX_RATE, po_balance, three_way_match
from .schemas import (
    Discrepancy,
    GoodsReceipt,
    Invoice,
    PastInvoice,
    PurchaseOrder,
    Route,
    Vendor,
    strictest,
)


@dataclass
class RuleDecision:
    route: Route
    discrepancies: list[Discrepancy] = field(default_factory=list)
    invoice_total: Decimal | None = None

    @property
    def money_at_risk(self) -> Decimal:
        return total_impact(self.discrepancies, cap=self.invoice_total)


def evaluate(po: PurchaseOrder, grn: GoodsReceipt, inv: Invoice, vendors: dict[str, Vendor],
             history: Iterable[PastInvoice] = (), price_tolerance: Decimal = Decimal("0"),
             max_tax_rate: Decimal | None = MAX_TAX_RATE) -> RuleDecision:
    history = list(history)
    issues = three_way_match(po, grn, inv, price_tolerance=price_tolerance, max_tax_rate=max_tax_rate)
    issues += po_balance(po, inv, history)
    issues += fraud_checks(inv, vendors, history, fallback_supplier_id=po.supplier_id)
    return RuleDecision(route=strictest([i.route for i in issues]), discrepancies=issues, invoice_total=inv.total)


def final_route(rule_route: Route, agent_route: Route | None) -> Route:
    """The agent may make a case stricter, never looser than the rules allow."""
    if agent_route is None:
        return rule_route
    return strictest([rule_route, agent_route])


def human_handoff(rule_route: Route, agent_route: Route | None, agent_answered: bool) -> list[Discrepancy]:
    """Findings that hand a case to a person when the two opinions don't line up.

    A clean invoice is only marked ready to pay when the checks AND a readable agent
    review both say so. When the agent is stricter than the checks, the finding says why
    the route went up, so the reviewer reads the agent's note.
    """
    if agent_route is None:
        if rule_route is not Route.APPROVE:
            return []  # already held or blocked by the checks
        why = "didn't answer" if not agent_answered else "gave a reply that couldn't be read as a decision"
        return [Discrepancy(code="LOW_CONFIDENCE", route=Route.HOLD, field="agent review",
                            message=f"The checks found nothing, but the agent {why}, so a person decides "
                                    "instead of marking it ready to pay.")]
    if agent_route.rank > rule_route.rank:
        return [Discrepancy(code="AGENT_CONCERN", route=agent_route, field="agent review",
                            message="The agent was stricter than the checks. Read its note before deciding.")]
    return []


def confidence_reasons(discrepancies: Iterable[Discrepancy]) -> list[str]:
    """Plain reasons the decision needs a person's judgement; empty means checks and agent agree."""
    labels = {"LOW_CONFIDENCE": "the agent's review didn't complete",
              "AGENT_CONCERN": "the agent and the checks disagree",
              "MISSING_FIELD": "some values couldn't be read from the documents"}
    codes = {d.code for d in discrepancies}
    return [text for code, text in labels.items() if code in codes]
