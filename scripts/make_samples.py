"""Generate the synthetic evaluation set: 24 cases of PO + GRN + invoice PDFs.

Each case folder holds po.pdf, grn.pdf, invoice.pdf and truth.json (the exact
values printed on the documents plus the expected route). All companies,
people and bank accounts are fictional.

    python scripts/make_samples.py            # writes data/samples/ and data/vendor_master.*
"""
from __future__ import annotations

import copy
import csv
import json
import random
import shutil
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "samples"
TODAY = date(2026, 10, 5)
random.seed(7)
rl_config.invariant = 1  # byte-identical PDFs on every run

VENDORS = [
    {"supplier_id": "V001", "name": "Acme Office Supplies Ltd", "iban": "GB82ACME00001234567801", "currency": "USD"},
    {"supplier_id": "V002", "name": "Northwind Electronics LLC", "iban": "US11NWND00000987654302", "currency": "USD"},
    {"supplier_id": "V003", "name": "Milano Arredi S.r.l.", "iban": "IT60MILA0000000000456703", "currency": "EUR"},
    {"supplier_id": "V004", "name": "Ravi Textiles Pvt Ltd", "iban": "PK36RAVI0000001122334404", "currency": "USD"},
    {"supplier_id": "V005", "name": "Helios Packaging GmbH", "iban": "DE89HELI0000000044556605", "currency": "EUR"},
]
VBY = {v["supplier_id"]: v for v in VENDORS}
PREFIX = {"V001": "AC", "V002": "NW", "V003": "MA", "V004": "RT", "V005": "HP"}

CATALOG = {
    "V001": [("CHR-100", "Ergonomic office chair", "20.00"), ("DSK-200", "Standing desk frame", "145.00"),
             ("PPR-A4", "A4 paper, box of 5 reams", "18.50")],
    "V002": [("LAP-14", "14-inch business laptop", "780.00"), ("MON-27", "27-inch monitor", "210.00"),
             ("DOC-USB", "USB-C docking station", "95.00")],
    "V003": [("TAV-180", "Meeting table 180 cm", "640.00"), ("SED-02", "Visitor chair", "85.00")],
    "V004": [("CTN-500", "Cotton fabric roll, 50 m", "120.00"), ("TWL-HT", "Hotel towel set", "14.25")],
    "V005": [("BOX-M", "Corrugated box, medium (pack of 100)", "38.00"), ("TAPE-48", "Packing tape 48 mm (36 rolls)", "42.00")],
}

# Invoices already processed last month (used for duplicate detection).
HISTORY = [
    {"supplier_id": "V002", "invoice_number": "NW-55120", "invoice_date": "2026-09-14", "total": "4440.00"},
    {"supplier_id": "V005", "invoice_number": "HP-3301", "invoice_date": "2026-09-28", "total": "1920.00"},
    {"supplier_id": "V001", "invoice_number": "AC-7710", "invoice_date": "2026-08-30", "total": "512.00"},
    # Billed all 10 docking stations ordered on PO-2026-1024 (see case 24).
    {"supplier_id": "V002", "invoice_number": "NW-7024", "invoice_date": "2026-09-22", "total": "950.00",
     "po_number": "PO-2026-1024", "lines": [{"sku": "DOC-USB", "qty": "10"}]},
]


def d(x) -> Decimal:
    return Decimal(str(x))


def money(x: Decimal) -> str:
    return f"{x.quantize(Decimal('0.01')):,.2f}"


def build_case(n: int, supplier: str, picks: list[tuple[int, int]], tax_rate: str = "0.00") -> dict:
    """picks = [(catalog_index, qty), ...] → a perfectly matching PO, GRN, invoice."""
    v = VBY[supplier]
    po_no = f"PO-2026-{1000 + n}"
    po_lines, grn_lines, inv_lines = [], [], []
    for idx, qty in picks:
        sku, desc, price = CATALOG[supplier][idx]
        po_lines.append({"sku": sku, "description": desc, "qty": str(qty), "unit_price": price})
        grn_lines.append({"sku": sku, "description": desc, "qty_received": str(qty)})
        inv_lines.append({"sku": sku, "description": desc, "qty": str(qty), "unit_price": price,
                          "line_total": str(d(qty) * d(price))})
    subtotal = sum(d(ln["line_total"]) for ln in inv_lines)
    tax = (subtotal * d(tax_rate)).quantize(Decimal("0.01"))
    po_date = TODAY - timedelta(days=20 + n % 5)
    return {
        "po": {"po_number": po_no, "po_date": po_date.isoformat(), "supplier_id": supplier,
               "supplier_name": v["name"], "currency": v["currency"], "lines": po_lines},
        "grn": {"grn_number": f"GRN-{5000 + n}", "po_number": po_no,
                "received_date": (po_date + timedelta(days=10)).isoformat(), "supplier_id": supplier,
                "lines": grn_lines},
        "invoice": {"invoice_number": f"{PREFIX.get(supplier, 'XX')}-{8000 + n}", "invoice_date": (TODAY + timedelta(days=n % 4)).isoformat(),
                    "po_number": po_no, "supplier_id": supplier, "supplier_name": v["name"],
                    "currency": v["currency"], "bank_iban": v["iban"], "lines": inv_lines,
                    "subtotal": str(subtotal), "tax": str(tax), "total": str(subtotal + tax)},
    }


def retotal(inv: dict) -> None:
    for ln in inv["lines"]:
        ln["line_total"] = str(d(ln["qty"]) * d(ln["unit_price"]))
    sub = sum(d(ln["line_total"]) for ln in inv["lines"])
    inv["subtotal"] = str(sub)
    inv["total"] = str(sub + d(inv["tax"]))


def cases() -> list[dict]:
    out = []

    def add(desc, route, codes, case):
        case.update({"description": desc, "expected_route": route, "expected_codes": codes})
        out.append(case)

    # Clean cases
    add("Clean three-way match", "approve_for_payment", [], build_case(1, "V001", [(1, 4), (2, 10)]))
    add("Clean three-way match", "approve_for_payment", [], build_case(2, "V002", [(0, 3), (2, 3)]))
    add("Clean three-way match, EUR with 22% VAT", "approve_for_payment", [], build_case(3, "V003", [(0, 1), (1, 6)], "0.22"))
    add("Clean three-way match", "approve_for_payment", [], build_case(4, "V004", [(0, 12)]))
    add("Clean three-way match, EUR with 19% VAT", "approve_for_payment", [], build_case(5, "V005", [(0, 20), (1, 5)], "0.19"))
    add("Clean three-way match", "approve_for_payment", [], build_case(6, "V002", [(1, 8)]))

    # Price variance: the $200 demo case
    c = build_case(7, "V001", [(0, 100)])
    c["invoice"]["lines"][0]["unit_price"] = "22.00"
    retotal(c["invoice"])
    add("Unit price $22 billed vs $20 on PO for 100 chairs ($200 overcharge)", "hold_for_review", ["PRICE_VARIANCE"], c)

    c = build_case(8, "V002", [(1, 5)])
    c["invoice"]["lines"][0]["unit_price"] = "214.50"
    retotal(c["invoice"])
    add("Small price increase on monitors", "hold_for_review", ["PRICE_VARIANCE"], c)

    c = build_case(9, "V004", [(1, 100)])
    c["grn"]["lines"][0]["qty_received"] = "90"
    add("Billed 100 towel sets, only 90 received", "hold_for_review", ["QTY_NOT_RECEIVED"], c)

    c = build_case(10, "V005", [(0, 10)])
    c["invoice"]["lines"][0]["qty"] = "12"
    c["grn"]["lines"][0]["qty_received"] = "12"
    retotal(c["invoice"])
    add("Billed 12 packs, PO ordered 10 (12 delivered)", "hold_for_review", ["QTY_OVER_PO"], c)

    c = build_case(11, "V001", [(2, 20)])
    c["invoice"]["lines"][0]["line_total"] = "390.00"
    c["invoice"]["subtotal"] = "390.00"
    c["invoice"]["total"] = "390.00"
    add("Line total wrong: 20 x 18.50 printed as 390.00", "hold_for_review", ["LINE_ARITHMETIC"], c)

    c = build_case(12, "V003", [(1, 10)], "0.22")
    c["invoice"]["total"] = str(d(c["invoice"]["subtotal"]) + d(c["invoice"]["tax"]) + d("100.00"))
    add("Total is 100 more than subtotal + VAT", "hold_for_review", ["TOTAL_ARITHMETIC"], c)

    c = build_case(13, "V002", [(0, 2)])
    c["invoice"]["lines"].append({"sku": "EXT-WTY", "description": "Extended warranty 3 years",
                                  "qty": "2", "unit_price": "120.00", "line_total": "240.00"})
    retotal(c["invoice"])
    add("Extra warranty line that is not on the PO", "hold_for_review", ["ITEM_NOT_ON_PO"], c)

    c = build_case(14, "V003", [(0, 2)])
    c["invoice"]["currency"] = "USD"
    add("Invoice in USD, PO in EUR", "hold_for_review", ["CURRENCY_MISMATCH"], c)

    # Fraud cases
    c = build_case(15, "V001", [(1, 6)])
    c["invoice"]["bank_iban"] = "GB15ZQRT00009876543215"
    add("Perfect invoice, but bank account changed (payment-diversion fraud)", "escalate_fraud", ["BANK_MISMATCH"], c)

    c = build_case(16, "V002", [(0, 5), (2, 5)])
    c["invoice"]["invoice_number"] = "NW-55120"
    c["invoice"]["total"] = c["invoice"]["subtotal"]
    add("Invoice number already paid last month", "escalate_fraud", ["DUPLICATE_INVOICE"], c)

    c = build_case(17, "V005", [(0, 30), (1, 18)])  # 30 x 38 + 18 x 42 = 1,896.00
    c["invoice"]["tax"] = "24.00"
    retotal(c["invoice"])  # total 1,920.00 = same as HP-3301
    add("Same amount as an invoice paid 1 week ago, new number", "escalate_fraud", ["POSSIBLE_DUPLICATE"], c)

    c = build_case(18, "V001", [(0, 10)])
    for doc in ("po", "grn", "invoice"):
        c[doc]["supplier_id"] = "V099"
    c["po"]["supplier_name"] = c["invoice"]["supplier_name"] = "Acme Office Suplies Ltd"
    add("Look-alike supplier not in vendor master", "escalate_fraud", ["UNKNOWN_VENDOR"], c)

    add("Clean three-way match", "approve_for_payment", [], build_case(19, "V004", [(0, 3), (1, 40)]))

    c = build_case(20, "V001", [(0, 5)])
    c["corrupt_invoice"] = True
    add("Invoice PDF is corrupt / unreadable", "processing_error", [], c)

    # Tricks a plain invoice-vs-PO check lets through
    c = build_case(21, "V001", [(2, 30)])
    c["invoice"]["invoice_number"] = "AC7710"
    add("Paid invoice AC-7710 sent again as AC7710 (dash removed)", "escalate_fraud", ["LOOKALIKE_INVOICE_NUMBER"], c)

    c = build_case(22, "V003", [(1, 8)])
    c["invoice"]["tax"] = "408.00"  # 60% of the 680.00 subtotal
    retotal(c["invoice"])
    add("Tax padded to 60% of the subtotal; the sums still add up", "hold_for_review", ["TAX_OUT_OF_RANGE"], c)

    c = build_case(23, "V004", [(0, 12)])
    c["invoice"]["lines"][0]["qty"] = "-2"
    retotal(c["invoice"])
    add("Credit note for 2 returned rolls sent in as an invoice", "hold_for_review", ["NEGATIVE_VALUE"], c)

    c = build_case(24, "V002", [(2, 10)])
    c["invoice"]["lines"][0]["qty"] = "4"
    retotal(c["invoice"])
    add("PO for 10 docks was fully billed last month; this invoice bills 4 more", "hold_for_review",
        ["PO_ALREADY_BILLED"], c)
    return out


# ---------------------------------------------------------------- PDF rendering
styles = getSampleStyleSheet()
GRID = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
                   ("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (2, 1), (-1, -1), "RIGHT")])


def _doc(path: Path, title: str, header: list[tuple[str, str]], table: list[list[str]], footer: list[tuple[str, str]]):
    story = [Paragraph(f"<b>{title}</b>", styles["Title"]), Spacer(1, 6)]
    hdr = Table([[k, v] for k, v in header], colWidths=[150, 330])
    hdr.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 10), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold")]))
    story += [hdr, Spacer(1, 14)]
    t = Table(table, colWidths=[70, 200, 50, 80, 80][: len(table[0])])
    t.setStyle(GRID)
    story += [t, Spacer(1, 12)]
    if footer:
        ft = Table([[k, v] for k, v in footer], colWidths=[400, 80])
        ft.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
        story.append(ft)
    SimpleDocTemplate(str(path), pagesize=A4, title=title).build(story)


def render(case: dict, folder: Path) -> None:
    po, grn, inv = case["po"], case["grn"], case["invoice"]
    cur = po["currency"]
    _doc(folder / "po.pdf", "PURCHASE ORDER",
         [("PO number", po["po_number"]), ("PO date", po["po_date"]), ("Buyer", "Brightline Retail Co."),
          ("Supplier", f'{po["supplier_name"]} (ID {po["supplier_id"]})'), ("Currency", cur)],
         [["SKU", "Description", "Qty", "Unit price", "Amount"]] +
         [[ln["sku"], ln["description"], ln["qty"], money(d(ln["unit_price"])), money(d(ln["qty"]) * d(ln["unit_price"]))] for ln in po["lines"]],
         [("PO value", money(sum(d(ln["qty"]) * d(ln["unit_price"]) for ln in po["lines"])))])
    _doc(folder / "grn.pdf", "GOODS RECEIVED NOTE",
         [("GRN number", grn["grn_number"]), ("Against PO", grn["po_number"]), ("Received on", grn["received_date"]),
          ("Supplier ID", grn["supplier_id"]), ("Checked by", "Warehouse, Gate 2")],
         [["SKU", "Description", "Qty received"]] + [[ln["sku"], ln["description"], ln["qty_received"]] for ln in grn["lines"]], [])
    if case.get("corrupt_invoice"):
        (folder / "invoice.pdf").write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj <<garbled>>\x00\x13\x87 truncated")
        return
    _doc(folder / "invoice.pdf", "TAX INVOICE",
         [("Invoice number", inv["invoice_number"]), ("Invoice date", inv["invoice_date"]),
          ("Supplier", f'{inv["supplier_name"]} (ID {inv["supplier_id"]})'), ("Bill to", "Brightline Retail Co."),
          ("Your PO", inv["po_number"]), ("Currency", inv["currency"]), ("Pay to IBAN", inv["bank_iban"])],
         [["SKU", "Description", "Qty", "Unit price", "Line total"]] +
         [[ln["sku"], ln["description"], ln["qty"], money(d(ln["unit_price"])), money(d(ln["line_total"]))] for ln in inv["lines"]],
         [("Subtotal", money(d(inv["subtotal"]))), ("Tax", money(d(inv["tax"]))), ("TOTAL DUE", money(d(inv["total"])))])


def write_vendor_master() -> None:
    with open(DATA / "vendor_master.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["supplier_id", "name", "iban", "currency"])
        w.writeheader()
        w.writerows(VENDORS)
    story = [Paragraph("<b>Brightline Retail Co. - Approved vendor master and AP policy</b>", styles["Title"]),
             Paragraph("Only these suppliers are approved. Payments may only go to the bank account listed here. "
                       "Bank detail changes must be confirmed by phone with a known contact before any payment.",
                       styles["Normal"]), Spacer(1, 10)]
    t = Table([["Supplier ID", "Name", "Bank account (IBAN)", "Currency"]] +
              [[v["supplier_id"], v["name"], v["iban"], v["currency"]] for v in VENDORS], colWidths=[60, 160, 190, 60])
    t.setStyle(GRID)
    story += [t, Spacer(1, 12), Paragraph("<b>Agreed price lists</b>", styles["Heading2"])]
    rows = [["Supplier", "SKU", "Description", "Agreed unit price"]]
    for sid, items in CATALOG.items():
        rows += [[sid, s, desc, p] for s, desc, p in items]
    pt = Table(rows, colWidths=[55, 70, 245, 100])
    pt.setStyle(GRID)
    story += [pt, Spacer(1, 12), Paragraph("<b>Tolerance rules</b>", styles["Heading2"]),
              Paragraph("Price tolerance: 0.00 (any variance is held). Quantities billed may not exceed quantities "
                        "ordered or received. Duplicate invoice numbers, or the same amount from the same supplier "
                        "within 30 days, are escalated as possible fraud.", styles["Normal"]),
              Paragraph("An invoice number that differs from a processed one only in punctuation, spacing, leading "
                        "zeros or look-alike characters is treated as a duplicate. Each ordered unit may be billed "
                        "once across all invoices for a purchase order. Tax above 30% of the subtotal is held. "
                        "Credit notes and negative amounts are held for a person. No payment is released without "
                        "a person's decision in the review queue.", styles["Normal"])]
    SimpleDocTemplate(str(DATA / "vendor_master.pdf"), pagesize=A4).build(story)
    (DATA / "history.json").write_text(json.dumps(HISTORY, indent=2))


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    write_vendor_master()
    all_cases = cases()
    for i, case in enumerate(all_cases, start=1):
        folder = OUT / f"case_{i:02d}"
        folder.mkdir()
        render(case, folder)
        truth = copy.deepcopy(case)
        truth["case_id"] = folder.name
        if truth.pop("corrupt_invoice", False):
            truth["invoice"] = None
        (folder / "truth.json").write_text(json.dumps(truth, indent=2))
    print(f"wrote {len(all_cases)} cases to {OUT}")


if __name__ == "__main__":
    main()
