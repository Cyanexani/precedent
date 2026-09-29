"""Generate the synthetic AP dataset used by Precedent.

Every total is computed from line items here, so the JSON files are internally
consistent. Edge cases are introduced deliberately and are listed in
`QUEUE_SCENARIOS` below. Run from the backend folder:

    python scripts/generate_data.py
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

COMPANY = {
    "name": "Nirmaan Foods Pvt Ltd",
    "gstin": "27AADCN5732R1Z4",
    "state": "Maharashtra",
    "state_code": "27",
    "address": "Plot 42, MIDC Chakan Phase II, Pune 410501",
    "financial_year": "2026-27",
}

VENDORS = [
    {"id": "V001", "name": "Shree Ganesh Packaging Pvt Ltd", "gstin": "27AAKCS8124F1Z6", "city": "Pune", "state": "Maharashtra", "state_code": "27", "category": "Corrugated packaging", "supply_type": "goods", "msme": True, "udyam_no": "UDYAM-MH-26-0048213", "payment_terms": "NET30", "onboarded_on": "2023-04-10", "bank": {"bank_name": "HDFC Bank", "account_last4": "4417", "ifsc": "HDFC0001289"}, "contact": {"name": "Ganesh Kulkarni", "phone": "+91 98220 41173"}},
    {"id": "V002", "name": "Krishna Steel Traders", "gstin": "24AAIFK3391L1ZP", "city": "Ahmedabad", "state": "Gujarat", "state_code": "24", "category": "Stainless steel sheets and fittings", "supply_type": "goods", "msme": False, "udyam_no": None, "payment_terms": "NET45", "onboarded_on": "2022-11-02", "bank": {"bank_name": "ICICI Bank", "account_last4": "7702", "ifsc": "ICIC0000451"}, "contact": {"name": "Hitesh Patel", "phone": "+91 98250 66120"}},
    {"id": "V003", "name": "Sai Balaji Electricals", "gstin": "27ABXPS6612H1ZK", "city": "Pune", "state": "Maharashtra", "state_code": "27", "category": "Electrical maintenance supplies", "supply_type": "goods", "msme": True, "udyam_no": "UDYAM-MH-26-0102277", "payment_terms": "NET30", "onboarded_on": "2024-01-15", "bank": {"bank_name": "State Bank of India", "account_last4": "2290", "ifsc": "SBIN0004418"}, "contact": {"name": "Balaji Shinde", "phone": "+91 97640 22381"}},
    {"id": "V004", "name": "Mehta Printers & Labels", "gstin": "27AAHFM2208Q1Z9", "city": "Mumbai", "state": "Maharashtra", "state_code": "27", "category": "Printed labels", "supply_type": "goods", "msme": True, "udyam_no": "UDYAM-MH-19-0031540", "payment_terms": "NET30", "onboarded_on": "2023-08-21", "bank": {"bank_name": "Kotak Mahindra Bank", "account_last4": "6634", "ifsc": "KKBK0000652"}, "contact": {"name": "Rakesh Mehta", "phone": "+91 98200 13457"}},
    {"id": "V005", "name": "Deccan Cold Chain Logistics Pvt Ltd", "gstin": "36AAECD7419B1ZX", "city": "Hyderabad", "state": "Telangana", "state_code": "36", "category": "Refrigerated transport", "supply_type": "services", "msme": False, "udyam_no": None, "payment_terms": "NET30", "onboarded_on": "2024-06-03", "bank": {"bank_name": "Axis Bank", "account_last4": "1187", "ifsc": "UTIB0000733"}, "contact": {"name": "Srinivas Reddy", "phone": "+91 99490 55218"}},
    {"id": "V006", "name": "Annapurna Agro Suppliers", "gstin": "27AAQFA5530M1ZC", "city": "Nashik", "state": "Maharashtra", "state_code": "27", "category": "Edible oils and agri inputs", "supply_type": "goods", "msme": False, "udyam_no": None, "payment_terms": "NET60", "onboarded_on": "2021-07-12", "bank": {"bank_name": "Bank of Maharashtra", "account_last4": "5098", "ifsc": "MAHB0000217"}, "contact": {"name": "Suresh Jadhav", "phone": "+91 94220 70914"}},
    {"id": "V007", "name": "Kaveri Lab Instruments", "gstin": "29AAGCK9087N1ZT", "city": "Bengaluru", "state": "Karnataka", "state_code": "29", "category": "Laboratory equipment", "supply_type": "goods", "msme": True, "udyam_no": "UDYAM-KA-03-0219954", "payment_terms": "NET30", "onboarded_on": "2026-09-15", "bank": {"bank_name": "Canara Bank", "account_last4": "0453", "ifsc": "CNRB0002671"}, "contact": {"name": "Deepa Raghavan", "phone": "+91 99801 38842"}},
    {"id": "V008", "name": "Vyom IT Solutions LLP", "gstin": "36AAPFV1123C1ZL", "city": "Hyderabad", "state": "Telangana", "state_code": "36", "category": "IT support and AMC", "supply_type": "services", "msme": False, "udyam_no": None, "payment_terms": "NET45", "onboarded_on": "2023-02-01", "bank": {"bank_name": "HDFC Bank", "account_last4": "3308", "ifsc": "HDFC0000521"}, "contact": {"name": "Karthik Varma", "phone": "+91 90000 48127"}},
    {"id": "V009", "name": "Pawar Industrial Supplies", "gstin": "27AFCPP4410D1ZM", "city": "Pune", "state": "Maharashtra", "state_code": "27", "category": "Industrial hardware", "supply_type": "goods", "msme": True, "udyam_no": "UDYAM-MH-26-0187730", "payment_terms": "NET30", "onboarded_on": "2024-10-07", "bank": {"bank_name": "Union Bank of India", "account_last4": "8841", "ifsc": "UBIN0531219"}, "contact": {"name": "Sachin Pawar", "phone": "+91 98901 27764"}},
]

ITEMS = {
    "BOX-5PLY": {"description": "5-ply corrugated box 18x12x10 in", "hsn": "4819", "unit": "pcs", "gst_rate": 18, "price": 35.0},
    "SS304-SHEET": {"description": "SS304 sheet 2 mm", "hsn": "7219", "unit": "kg", "gst_rate": 18, "price": 238.0},
    "MCB-32A": {"description": "MCB 32A double pole", "hsn": "8536", "unit": "pcs", "gst_rate": 18, "price": 540.0},
    "CABLE-4SQ": {"description": "Copper cable 4 sq mm, 90 m coil", "hsn": "8544", "unit": "coil", "gst_rate": 18, "price": 4850.0},
    "LBL-ROLL": {"description": "Printed BOPP label roll, 1000 labels", "hsn": "4821", "unit": "roll", "gst_rate": 18, "price": 1150.0},
    "REEFER-TRIP": {"description": "Reefer truck trip Hyderabad to Pune, 20 ft", "hsn": "9965", "unit": "trip", "gst_rate": 12, "price": 38500.0},
    "SFO-15L": {"description": "Refined sunflower oil, 15 L tin", "hsn": "1512", "unit": "tin", "gst_rate": 5, "price": 1250.0},
    "MOIST-AN": {"description": "Moisture analyzer MA-110", "hsn": "9027", "unit": "pcs", "gst_rate": 18, "price": 120000.0},
    "IT-AMC": {"description": "IT infrastructure AMC, monthly", "hsn": "9987", "unit": "month", "gst_rate": 18, "price": 50000.0},
    "PALLET-TRK": {"description": "Hand pallet truck 2.5 T", "hsn": "8427", "unit": "pcs", "gst_rate": 18, "price": 14500.0},
}

TERMS_DAYS = {"IMMEDIATE": 0, "NET15": 15, "NET30": 30, "NET45": 45, "NET60": 60}

PAYMENT_TERMS = [
    {"code": "IMMEDIATE", "days": 0, "description": "Payable on receipt"},
    {"code": "NET15", "days": 15, "description": "Payable within 15 days of invoice date"},
    {"code": "NET30", "days": 30, "description": "Payable within 30 days of invoice date"},
    {"code": "NET45", "days": 45, "description": "Payable within 45 days of invoice date"},
    {"code": "NET60", "days": 60, "description": "Payable within 60 days of invoice date"},
]

APPROVAL_RULES = {
    "currency": "INR",
    "tiers": [
        {"max_amount": 100000, "approver_role": "AP Executive", "level": 1},
        {"max_amount": 500000, "approver_role": "Finance Manager", "level": 2},
        {"max_amount": None, "approver_role": "CFO", "level": 3},
    ],
    "escalations": [
        {"when": "new_vendor", "min_level": 2, "reason": "Vendor onboarded less than 90 days ago"},
        {"when": "high_severity_finding", "min_level": 2, "reason": "Invoice has a high severity exception"},
        {"when": "bank_details_changed", "min_level": 3, "reason": "Bank details differ from vendor master"},
        {"when": "missing_po", "min_level": 2, "reason": "Non-PO invoice needs cost centre owner approval"},
    ],
    "tolerances": {
        "price_variance_pct": 2.0,
        "amount_spike_ratio": 1.4,
        "amount_low_ratio": 0.6,
        "baseline_min_invoices": 3,
        "duplicate_amount_pct": 1.0,
        "duplicate_window_days": 10,
        "new_vendor_days": 90,
        "rounding_tolerance_inr": 1.0,
    },
    "gst_rates": [0, 5, 12, 18, 28],
    "msme_max_payment_days": 45,
}


def r2(x: float) -> float:
    return round(x + 1e-9, 2)


def vendor(vid: str) -> dict:
    return next(v for v in VENDORS if v["id"] == vid)


def make_lines(spec: list[tuple], price_override: dict | None = None) -> list[dict]:
    lines = []
    for item_code, qty in spec:
        item = ITEMS[item_code]
        price = (price_override or {}).get(item_code, item["price"])
        lines.append({
            "item_code": item_code,
            "description": item["description"],
            "hsn": item["hsn"],
            "unit": item["unit"],
            "qty": qty,
            "unit_price": price,
            "gst_rate": item["gst_rate"],
            "amount": r2(qty * price),
        })
    return lines


def make_tax(lines: list[dict], vid: str, force_head: str | None = None) -> dict:
    """Correct GST split unless force_head overrides it (used for the tax mismatch case)."""
    intra = vendor(vid)["state_code"] == COMPANY["state_code"]
    head = force_head or ("CGST_SGST" if intra else "IGST")
    cgst = sgst = igst = 0.0
    for ln in lines:
        tax = ln["amount"] * ln["gst_rate"] / 100
        if head == "IGST":
            igst += tax
        else:
            cgst += tax / 2
            sgst += tax / 2
    return {"cgst": r2(cgst), "sgst": r2(sgst), "igst": r2(igst)}


def make_invoice(inv_id, invoice_no, vid, inv_date: date, po_id, lines, *, status, terms=None,
                 tax=None, bank_last4=None, grn_id=None, paid_on=None, notes=None, due_days=None):
    v = vendor(vid)
    terms = terms or v["payment_terms"]
    tax = tax or make_tax(lines, vid)
    subtotal = r2(sum(ln["amount"] for ln in lines))
    tax_total = r2(tax["cgst"] + tax["sgst"] + tax["igst"])
    days = TERMS_DAYS[terms] if due_days is None else due_days
    return {
        "id": inv_id,
        "invoice_no": invoice_no,
        "vendor_id": vid,
        "invoice_date": inv_date.isoformat(),
        "received_date": (inv_date + timedelta(days=2)).isoformat(),
        "po_id": po_id,
        "grn_id": grn_id,
        "lines": lines,
        "tax": tax,
        "subtotal": subtotal,
        "tax_total": tax_total,
        "total": r2(subtotal + tax_total),
        "payment_terms": terms,
        "due_date": (inv_date + timedelta(days=days)).isoformat(),
        "bank_account_last4": bank_last4 or v["bank"]["account_last4"],
        "status": status,
        "paid_on": paid_on,
        "notes": notes,
    }


def make_po(po_id, vid, po_date: date, lines, amendments=None, requested_by="Stores, Chakan plant"):
    return {
        "id": po_id,
        "vendor_id": vid,
        "po_date": po_date.isoformat(),
        "status": "open",
        "requested_by": requested_by,
        "lines": [{k: ln[k] for k in ("item_code", "description", "hsn", "unit", "qty", "unit_price", "gst_rate")} for ln in lines],
        "amendments": amendments or [],
    }


def make_grn(grn_id, po_id, grn_date: date, received: list[tuple]):
    return {
        "id": grn_id,
        "po_id": po_id,
        "grn_date": grn_date.isoformat(),
        "received_by": "Stores, Chakan plant",
        "lines": [{"item_code": code, "qty_received": qty} for code, qty in received],
    }


def build():
    pos, grns, invoices = [], [], []
    seq = {"po": 700, "grn": 600, "inv": 1}

    def next_po():
        seq["po"] += 7
        return f"NF/PO/26-27/{seq['po']:04d}"

    def next_grn():
        seq["grn"] += 5
        return f"NF/GRN/26-27/{seq['grn']:04d}"

    def add_history(vid, prefix, number, inv_date, spec, price_override=None, service=False):
        lines = make_lines(spec, price_override)
        po_id = next_po()
        pos.append(make_po(po_id, vid, inv_date - timedelta(days=12), lines))
        grn_id = None
        if not service:
            grn_id = next_grn()
            grns.append(make_grn(grn_id, po_id, inv_date - timedelta(days=1), spec))
        inv = make_invoice(f"H-{seq['inv']:03d}", f"{prefix}/26-27/{number:04d}", vid, inv_date, po_id, lines,
                           status="paid", grn_id=grn_id,
                           paid_on=(inv_date + timedelta(days=TERMS_DAYS[vendor(vid)["payment_terms"]] - 3)).isoformat())
        seq["inv"] += 1
        invoices.append(inv)
        return inv

    # ---------- Paid history (vendor baselines, duplicate detection) ----------
    for i, (d, qty) in enumerate([(date(2026, 4, 9), 1200), (date(2026, 5, 11), 1300), (date(2026, 6, 10), 1250),
                                  (date(2026, 7, 9), 1400), (date(2026, 8, 7), 1150)]):
        add_history("V001", "SGP", 101 + i * 61, d, [("BOX-5PLY", qty)])
    for i, (d, qty) in enumerate([(date(2026, 4, 22), 500), (date(2026, 5, 27), 620), (date(2026, 6, 24), 540),
                                  (date(2026, 8, 19), 580)]):
        add_history("V002", "KST", 211 + i * 37, d, [("SS304-SHEET", qty)])
    for i, (d, mcb, cable) in enumerate([(date(2026, 4, 15), 20, 1), (date(2026, 5, 18), 16, 2),
                                         (date(2026, 7, 14), 22, 1), (date(2026, 8, 20), 18, 2)]):
        add_history("V003", "SBE", 120 + i * 29, d, [("MCB-32A", mcb), ("CABLE-4SQ", cable)])
    for i, (d, rolls) in enumerate([(date(2026, 5, 16), 36), (date(2026, 6, 20), 42), (date(2026, 7, 18), 38)]):
        add_history("V004", "MPL", 905 + i * 91, d, [("LBL-ROLL", rolls)])
    mehta_original = add_history("V004", "MPL", 1187, date(2026, 8, 18), [("LBL-ROLL", 40)])
    for i, d in enumerate([date(2026, 5, 8), date(2026, 6, 26), date(2026, 8, 12)]):
        add_history("V005", "DCC", 170 + i * 23, d, [("REEFER-TRIP", 1)], service=True)
    for i, (d, tins) in enumerate([(date(2026, 4, 28), 480), (date(2026, 5, 29), 500), (date(2026, 7, 1), 450),
                                   (date(2026, 8, 3), 520)]):
        add_history("V006", "AAS", 240 + i * 17, d, [("SFO-15L", tins)])
    for i, d in enumerate([date(2026, 5, 31), date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31)]):
        add_history("V008", "VIT", 60 + i * 11, d, [("IT-AMC", 1)], service=True)
    for i, (d, n) in enumerate([(date(2026, 5, 21), 3), (date(2026, 7, 2), 2), (date(2026, 8, 26), 3)]):
        add_history("V009", "PIS", 330 + i * 26, d, [("PALLET-TRK", n)])

    # ---------- Pending queue (the demo) ----------
    queue = []

    def add_queue(inv_id, invoice_no, vid, inv_date, spec, *, po=None, grn=None, scenario, **kw):
        lines = make_lines(spec, kw.pop("price_override", None))
        po_id = grn_id = None
        if po:
            po_id = next_po()
            po_lines = make_lines(po["spec"], None)
            pos.append(make_po(po_id, vid, po["date"], po_lines, po.get("amendments")))
        if grn:
            grn_id = next_grn()
            grns.append(make_grn(grn_id, po_id, grn["date"], grn["received"]))
        tax = make_tax(lines, vid, kw.pop("force_head", None))
        inv = make_invoice(inv_id, invoice_no, vid, inv_date, kw.pop("po_override", po_id), lines,
                           status="pending", tax=tax, grn_id=grn_id, **kw)
        inv["scenario"] = scenario
        queue.append(inv)
        return inv

    # 1. Shree Ganesh bulk order: amount spike, PO amended, GRN matches (first-time exception)
    add_queue("INV-2001", "SGP/26-27/0412", "V001", date(2026, 9, 8), [("BOX-5PLY", 2000)],
              po={"date": date(2026, 8, 20), "spec": [("BOX-5PLY", 2000)],
                  "amendments": [{"date": "2026-08-28", "by": "Rohan Kulkarni, Procurement",
                                  "change": "BOX-5PLY quantity revised from 1,200 to 2,000 pcs",
                                  "reason": "Festive season dispatch plan, bulk order"}]},
              grn={"date": date(2026, 9, 6), "received": [("BOX-5PLY", 2000)]},
              scenario="Amount spike backed by an amended PO (first time)")
    # 2. Shree Ganesh again: similar spike, PO amended again (memory should recall #1)
    add_queue("INV-2002", "SGP/26-27/0539", "V001", date(2026, 9, 24), [("BOX-5PLY", 2200)],
              po={"date": date(2026, 9, 10), "spec": [("BOX-5PLY", 2200)],
                  "amendments": [{"date": "2026-09-16", "by": "Rohan Kulkarni, Procurement",
                                  "change": "BOX-5PLY quantity revised from 1,300 to 2,200 pcs",
                                  "reason": "Festive season dispatch plan, bulk order"}]},
              grn={"date": date(2026, 9, 22), "received": [("BOX-5PLY", 2200)]},
              scenario="Repeat amount spike, PO amended again")
    # 3. Shree Ganesh twist: spike without PO backing, GRN short
    add_queue("INV-2003", "SGP/26-27/0581", "V001", date(2026, 9, 27), [("BOX-5PLY", 2100)],
              po={"date": date(2026, 9, 18), "spec": [("BOX-5PLY", 1200)]},
              grn={"date": date(2026, 9, 26), "received": [("BOX-5PLY", 1200)]},
              scenario="Amount spike NOT backed by PO or goods receipt")
    # 4. Normal invoice
    add_queue("INV-2004", "SBE/26-27/0241", "V003", date(2026, 9, 16), [("MCB-32A", 18), ("CABLE-4SQ", 1)],
              po={"date": date(2026, 9, 4), "spec": [("MCB-32A", 18), ("CABLE-4SQ", 1)]},
              grn={"date": date(2026, 9, 15), "received": [("MCB-32A", 18), ("CABLE-4SQ", 1)]},
              scenario="Clean three-way match")
    # 5. Price variance 4.2% over PO
    add_queue("INV-2005", "KST/26-27/0402", "V002", date(2026, 9, 19), [("SS304-SHEET", 560)],
              price_override={"SS304-SHEET": 248.0},
              po={"date": date(2026, 9, 2), "spec": [("SS304-SHEET", 560)]},
              grn={"date": date(2026, 9, 17), "received": [("SS304-SHEET", 560)]},
              scenario="Unit price 4.2% above PO")
    # 6. Duplicate resubmission with /R1 suffix of an already paid invoice
    dup = make_invoice("INV-2006", "MPL/26-27/1187/R1", "V004", date(2026, 8, 18), mehta_original["po_id"],
                       make_lines([("LBL-ROLL", 40)]), status="pending", grn_id=mehta_original["grn_id"],
                       notes="Resubmitted copy. Payment not received as per our records.")
    dup["scenario"] = "Possible duplicate of a paid invoice"
    queue.append(dup)
    # 7. IGST charged on an intra-state supply
    add_queue("INV-2007", "PIS/26-27/0409", "V009", date(2026, 9, 18), [("PALLET-TRK", 3)],
              po={"date": date(2026, 9, 5), "spec": [("PALLET-TRK", 3)]},
              grn={"date": date(2026, 9, 17), "received": [("PALLET-TRK", 3)]},
              force_head="IGST", scenario="IGST on an intra-state supply")
    # 8. No PO (ad-hoc reefer trip)
    add_queue("INV-2008", "DCC/26-27/0256", "V005", date(2026, 9, 21), [("REEFER-TRIP", 1)],
              scenario="Service invoice without a purchase order")
    # 9. Above the CFO threshold, otherwise clean
    add_queue("INV-2009", "AAS/26-27/0318", "V006", date(2026, 9, 12), [("SFO-15L", 520)],
              po={"date": date(2026, 8, 30), "spec": [("SFO-15L", 520)]},
              grn={"date": date(2026, 9, 11), "received": [("SFO-15L", 520)]},
              scenario="Above CFO approval threshold")
    # 10. New MSME vendor quoting NET60 on its invoice
    add_queue("INV-2010", "KLI/26-27/0007", "V007", date(2026, 9, 23), [("MOIST-AN", 1)],
              po={"date": date(2026, 9, 16), "spec": [("MOIST-AN", 1)]},
              grn={"date": date(2026, 9, 22), "received": [("MOIST-AN", 1)]},
              terms="NET60", scenario="New MSME vendor, invoice terms beyond 45 days")
    # 11. Bank account differs from vendor master
    add_queue("INV-2011", "VIT/26-27/0104", "V008", date(2026, 9, 28), [("IT-AMC", 1)],
              po={"date": date(2026, 9, 1), "spec": [("IT-AMC", 1)]},
              bank_last4="9921", notes="Please note our updated bank details for this and future payments.",
              scenario="Bank details changed on invoice")
    # 12. Unusually low: partial delivery against a bigger PO
    add_queue("INV-2012", "SBE/26-27/0258", "V003", date(2026, 9, 25), [("MCB-32A", 10)],
              po={"date": date(2026, 9, 12), "spec": [("MCB-32A", 60)]},
              grn={"date": date(2026, 9, 24), "received": [("MCB-32A", 10)]},
              scenario="Unusually low amount, partial delivery")

    return pos, grns, invoices + queue


# Past exceptions the AP team resolved before this app existed. The "Load team
# history" action retains these into Hindsight. The Shree Ganesh spike story is
# deliberately absent so the live demo starts without that precedent.
HISTORICAL_CASES = [
    {"case_id": "CASE-KST-26-27-0318", "vendor_id": "V002", "invoice_no": "KST/26-27/0318", "invoice_date": "2026-07-14",
     "resolved_on": "2026-07-18", "reviewer": "Priya Nair", "total": 152278.8, "exception_codes": ["PRICE_VARIANCE"],
     "decision": "approve_with_conditions",
     "summary": "SS304 sheet billed at Rs 246 per kg against PO rate Rs 238 per kg, a 3.4% variance above the 2% tolerance.",
     "reason": "Rate contract RC-KST-2026 has a steel price escalation clause that allows pass-through of up to 5% when the JPC stainless index rises. Anil Deshmukh from procurement confirmed the index movement for July.",
     "evidence": ["Rate contract clause 7.2 checked", "JPC index sheet for July attached", "Procurement confirmation email"],
     "conditions": ["Variance above 5% must be rejected", "Attach the index sheet to every escalated invoice"]},
    {"case_id": "CASE-SBE-26-27-0144", "vendor_id": "V003", "invoice_no": "SBE/26-27/0144", "invoice_date": "2026-06-02",
     "resolved_on": "2026-06-05", "reviewer": "Arjun Menon", "total": 21712.0, "exception_codes": ["GST_MISMATCH"],
     "decision": "reject",
     "summary": "Pune vendor charged IGST 18% on a supply to our Pune plant. Place of supply is Maharashtra, so CGST 9% plus SGST 9% was due.",
     "reason": "Wrong tax head blocks our input tax credit. Vendor issued credit note CN/26-27/014 and reissued the invoice with CGST and SGST, which was then paid.",
     "evidence": ["Vendor GSTIN state code 27 matches ours", "Credit note received", "Corrected invoice received"],
     "conditions": []},
    {"case_id": "CASE-MPL-26-27-0942-R1", "vendor_id": "V004", "invoice_no": "MPL/26-27/0942/R1", "invoice_date": "2026-06-01",
     "resolved_on": "2026-06-12", "reviewer": "Priya Nair", "total": 41300.0, "exception_codes": ["DUPLICATE_SUSPECTED"],
     "decision": "reject",
     "summary": "Invoice MPL/26-27/0942/R1 had the same amount, date and PO as MPL/26-27/0942, which was already paid on 2026-06-02.",
     "reason": "Vendor billing team resubmitted with an /R1 suffix after their payment reconciliation lagged. Confirmed UTR of the original payment with the vendor and rejected the copy.",
     "evidence": ["Original payment UTR shared with vendor", "Vendor confirmed resubmission in error"],
     "conditions": ["Ask vendor to check the supplier payment portal before resubmitting"]},
    {"case_id": "CASE-DCC-26-27-0211", "vendor_id": "V005", "invoice_no": "DCC/26-27/0211", "invoice_date": "2026-06-29",
     "resolved_on": "2026-07-02", "reviewer": "Arjun Menon", "total": 43120.0, "exception_codes": ["MISSING_PO"],
     "decision": "approve_with_conditions",
     "summary": "Ad-hoc reefer truck trip billed without a purchase order during a cold storage breakdown at the Chakan plant.",
     "reason": "Plant head Sunita Rao gave written retro approval for the emergency trip. The rate matched the last three Deccan Cold Chain trips.",
     "evidence": ["Retro approval email from plant head", "Trip sheet and delivery challan", "Rate compared with previous trips"],
     "conditions": ["Retro PO to be raised within 7 days", "Recurring ad-hoc trips should move to a rate contract"]},
    {"case_id": "CASE-AAS-26-27-0287", "vendor_id": "V006", "invoice_no": "AAS/26-27/0287", "invoice_date": "2026-08-08",
     "resolved_on": "2026-08-11", "reviewer": "Priya Nair", "total": 525000.0, "exception_codes": ["BANK_DETAILS_CHANGED"],
     "decision": "reject",
     "summary": "Invoice arrived by email asking for payment to a new ICICI account instead of the Bank of Maharashtra account on the vendor master.",
     "reason": "Call-back to the phone number on the vendor master confirmed Annapurna Agro had NOT changed banks. The email came from a look-alike domain. This was an attempted payment diversion fraud and was reported to IT security.",
     "evidence": ["Call-back on vendor master phone number", "Email header check showed look-alike domain", "Reported to IT security"],
     "conditions": ["Never update bank details from an invoice or email", "Always call back on the vendor master number before paying a changed account"]},
    {"case_id": "CASE-AAS-26-27-0206", "vendor_id": "V006", "invoice_no": "AAS/26-27/0206", "invoice_date": "2026-05-19",
     "resolved_on": "2026-05-22", "reviewer": "Priya Nair", "total": 656250.0, "exception_codes": ["APPROVAL_CFO"],
     "decision": "approve",
     "summary": "Sunflower oil invoice above Rs 5 lakh routed to the CFO for approval after a clean three-way match.",
     "reason": "Seasonal oil stocking ahead of the monsoon production plan. CFO Rajesh Iyer approved and asked AP to bundle such invoices into the weekly CFO approval batch.",
     "evidence": ["Three-way match clean", "CFO approval on weekly batch"],
     "conditions": ["Route large edible oil invoices through the weekly CFO batch"]},
]


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pos, grns, invoices = build()
    out = {
        "company.json": COMPANY,
        "vendors.json": VENDORS,
        "purchase_orders.json": pos,
        "goods_receipts.json": grns,
        "invoices.json": invoices,
        "payment_terms.json": PAYMENT_TERMS,
        "approval_rules.json": APPROVAL_RULES,
        "historical_cases.json": HISTORICAL_CASES,
    }
    for name, payload in out.items():
        (DATA_DIR / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    pending = [i for i in invoices if i["status"] == "pending"]
    print(f"Wrote {len(VENDORS)} vendors, {len(pos)} POs, {len(grns)} GRNs, {len(invoices)} invoices "
          f"({len(pending)} pending), {len(HISTORICAL_CASES)} historical cases to {DATA_DIR}")


if __name__ == "__main__":
    main()
