"""Data contracts for LedgerPilot.

Every value that comes out of a document extractor is validated here before any
business rule touches it. Money is always Decimal, never float. Parsing is
lenient about formatting (symbols, thousands separators, decimal commas, common
date formats) but strict about meaning: anything that can't be read becomes
None, and missing data is sent to a person, never guessed.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_NUM_CHARS = re.compile(r"[^0-9,.\-]")


def to_decimal(value: Any) -> Optional[Decimal]:
    """Parse money/quantity values.

    Handles '1,250.00', '1.250,00', '$22', '22,5', '100 pcs', '(200.00)', 22, None.
    Raises ValueError when there is no number at all ('twelve hundred').
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    negative = (text.startswith("(") and text.endswith(")")) or text.startswith("-") or text.endswith("-")
    digits = _NUM_CHARS.sub("", text).replace("-", "")
    if not re.search(r"\d", digits):
        raise ValueError(f"not a number: {value!r}")
    if "," in digits and "." in digits:
        if digits.rfind(",") > digits.rfind("."):          # 1.250,50 (European)
            digits = digits.replace(".", "").replace(",", ".")
        else:                                              # 1,250.50
            digits = digits.replace(",", "")
    elif "," in digits:
        head, _, tail = digits.rpartition(",")
        if digits.count(",") == 1 and len(tail) in (1, 2):  # 22,5 or 22,50 (decimal comma)
            digits = f"{head}.{tail}"
        else:                                              # 1,250 or 1,250,000 (thousands)
            digits = digits.replace(",", "")
    elif digits.count(".") > 1:                            # 1.250.000 (thousands)
        digits = digits.replace(".", "")
    try:
        number = Decimal(digits)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc
    return -number if negative else number


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y",
                 "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%d %b, %Y")


def to_date(value: Any) -> Optional[date]:
    """Parse common invoice date formats. Ambiguous 05/10/2026 is read day-first
    (the convention in Pakistan, Italy and most of Europe). Unreadable -> None,
    which the rules engine treats as a missing field."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = re.sub(r"\s+", " ", str(value).strip())
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)
    if "T" in text and text[:4].isdigit():
        text = text.split("T", 1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _decimal_validator(*fields: str):
    return field_validator(*fields, mode="before")(lambda v: to_decimal(v))


class _Base(BaseModel):
    # Extractors sometimes return IDs as numbers (PO 12345): accept them as text.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True, coerce_numbers_to_str=True)


def _lines_or_empty(v: Any) -> Any:
    return [] if v is None else v


class POLine(_Base):
    sku: Optional[str] = None
    description: Optional[str] = None
    qty: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None

    _dec = _decimal_validator("qty", "unit_price")


class GRNLine(_Base):
    sku: Optional[str] = None
    description: Optional[str] = None
    qty_received: Optional[Decimal] = None

    _dec = _decimal_validator("qty_received")


class InvoiceLine(_Base):
    sku: Optional[str] = None
    description: Optional[str] = None
    qty: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    line_total: Optional[Decimal] = None

    _dec = _decimal_validator("qty", "unit_price", "line_total")


class PurchaseOrder(_Base):
    po_number: Optional[str] = None
    po_date: Optional[date] = None
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    currency: Optional[str] = None
    lines: list[POLine] = Field(default_factory=list)

    _date = field_validator("po_date", mode="before")(lambda v: to_date(v))
    _lines = field_validator("lines", mode="before")(_lines_or_empty)
    _cur = field_validator("currency", mode="before")(lambda v: _currency(v))


class GoodsReceipt(_Base):
    grn_number: Optional[str] = None
    po_number: Optional[str] = None
    received_date: Optional[date] = None
    supplier_id: Optional[str] = None
    lines: list[GRNLine] = Field(default_factory=list)

    _date = field_validator("received_date", mode="before")(lambda v: to_date(v))
    _lines = field_validator("lines", mode="before")(_lines_or_empty)


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

    _dec = _decimal_validator("subtotal", "tax", "total")
    _date = field_validator("invoice_date", mode="before")(lambda v: to_date(v))
    _lines = field_validator("lines", mode="before")(_lines_or_empty)

    @field_validator("bank_iban", mode="before")
    @classmethod
    def _clean_iban(cls, v: Any) -> Optional[str]:
        return None if v in (None, "") else re.sub(r"[\s\-]", "", str(v)).upper()

    @field_validator("currency", mode="before")
    @classmethod
    def _clean_currency(cls, v: Any) -> Optional[str]:
        return _currency(v)


def _currency(v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    text = str(v).strip().upper()
    return {"$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "RS": "PKR", "RS.": "PKR"}.get(text, text)


class Vendor(_Base):
    supplier_id: str
    name: str
    iban: str
    currency: str

    @field_validator("iban", mode="before")
    @classmethod
    def _clean_iban(cls, v: Any) -> str:
        return re.sub(r"[\s\-]", "", str(v)).upper()


class PastInvoice(_Base):
    """A previously processed invoice, used for duplicate detection."""

    supplier_id: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    total: Optional[Decimal] = None

    _dec = _decimal_validator("total")
    _date = field_validator("invoice_date", mode="before")(lambda v: to_date(v))


class Route(str, Enum):
    """Ordered from least to most severe. A route can only ever be raised."""

    APPROVE = "approve_for_payment"
    HOLD = "hold_for_review"
    FRAUD = "escalate_fraud"
    ERROR = "processing_error"

    @property
    def rank(self) -> int:
        return _RANK[self.value]


_RANK = {"approve_for_payment": 0, "hold_for_review": 1, "escalate_fraud": 2, "processing_error": 3}


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
