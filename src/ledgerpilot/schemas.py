"""Data contracts for LedgerPilot.

Every value that comes out of a document extractor is validated here before any
business rule touches it. Money is always Decimal, never float.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Parse money/quantity values like '1,250.00', '$22', 22, None."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    for symbol in ("$", "€", "£", "PKR", "Rs", "USD", "EUR"):
        text = text.replace(symbol, "")
    text = text.replace(",", "").replace(" ", "")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class POLine(_Base):
    sku: Optional[str] = None
    description: Optional[str] = None
    qty: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None

    _dec = field_validator("qty", "unit_price", mode="before")(_to_decimal)


class GRNLine(_Base):
    sku: Optional[str] = None
    description: Optional[str] = None
    qty_received: Optional[Decimal] = None

    _dec = field_validator("qty_received", mode="before")(_to_decimal)


class InvoiceLine(_Base):
    sku: Optional[str] = None
    description: Optional[str] = None
    qty: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    line_total: Optional[Decimal] = None

    _dec = field_validator("qty", "unit_price", "line_total", mode="before")(_to_decimal)


class PurchaseOrder(_Base):
    po_number: Optional[str] = None
    po_date: Optional[date] = None
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    currency: Optional[str] = None
    lines: list[POLine] = Field(default_factory=list)


class GoodsReceipt(_Base):
    grn_number: Optional[str] = None
    po_number: Optional[str] = None
    received_date: Optional[date] = None
    supplier_id: Optional[str] = None
    lines: list[GRNLine] = Field(default_factory=list)


class Invoice(_Base):
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    po_number: Optional[str] = None
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    currency: Optional[str] = None
    bank_iban: Optional[str] = None
    lines: list[InvoiceLine] = Field(default_factory=list)
    subtotal: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    total: Optional[Decimal] = None

    _dec = field_validator("subtotal", "tax", "total", mode="before")(_to_decimal)

    @field_validator("bank_iban", mode="before")
    @classmethod
    def _clean_iban(cls, v: Any) -> Optional[str]:
        return None if v in (None, "") else str(v).replace(" ", "").upper()


class Vendor(_Base):
    supplier_id: str
    name: str
    iban: str
    currency: str

    @field_validator("iban", mode="before")
    @classmethod
    def _clean_iban(cls, v: Any) -> str:
        return str(v).replace(" ", "").upper()


class PastInvoice(_Base):
    """A previously processed invoice, used for duplicate detection."""

    supplier_id: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    total: Optional[Decimal] = None

    _dec = field_validator("total", mode="before")(_to_decimal)


class Route(str, Enum):
    """Ordered from least to most severe. A route can only ever be raised."""

    APPROVE = "approve_for_payment"
    HOLD = "hold_for_review"
    FRAUD = "escalate_fraud"
    ERROR = "processing_error"

    @property
    def rank(self) -> int:
        return {"approve_for_payment": 0, "hold_for_review": 1, "escalate_fraud": 2, "processing_error": 3}[self.value]


class Discrepancy(_Base):
    code: str
    route: Route
    field: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    impact: Optional[Decimal] = None  # money at risk, in invoice currency
    message: str

    def as_row(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "route": self.route.value,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "impact": str(self.impact) if self.impact is not None else None,
            "message": self.message,
        }


def strictest(routes: list[Route]) -> Route:
    if not routes:
        return Route.APPROVE
    return max(routes, key=lambda r: r.rank)
