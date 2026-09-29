"""Deterministic AP checks.

No LLM here. Arithmetic, PO and goods receipt matching, GST, duplicates, vendor
baselines, payment terms and approval routing are all plain code so they are
reproducible and testable. The agent only explains what these checks found.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from .data_store import DataStore

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3}
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
RESUBMIT_SUFFIX_RE = re.compile(r"[/\-_ ]?(R\d+|REV\d*|COPY|DUP|DUPLICATE)$")
TERMS_DAYS = {"IMMEDIATE": 0, "NET15": 15, "NET30": 30, "NET45": 45, "NET60": 60}


@dataclass
class Finding:
    code: str
    severity: str
    title: str
    detail: str
    evidence: dict = field(default_factory=dict)


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _inr(x: float) -> str:
    """Indian digit grouping, e.g. 682500 -> 6,82,500."""
    neg, x = x < 0, abs(round(x, 2))
    whole, frac = f"{x:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    out = ",".join(groups + [tail]) if groups else tail
    out = f"Rs {out}" + (f".{frac}" if frac != "00" else "")
    return f"-{out}" if neg else out


# ---------------------------------------------------------------- individual checks


def check_arithmetic(inv: dict, tol: float) -> list[Finding]:
    out = []
    for ln in inv["lines"]:
        expected = round(ln["qty"] * ln["unit_price"], 2)
        if abs(expected - ln["amount"]) > tol:
            out.append(Finding("ARITHMETIC_MISMATCH", "high", "Line amount does not equal qty x rate",
                               f"{ln['description']}: {ln['qty']} x {ln['unit_price']} = {expected}, invoice shows {ln['amount']}.",
                               {"item_code": ln["item_code"], "expected": expected, "stated": ln["amount"]}))
    subtotal = round(sum(ln["amount"] for ln in inv["lines"]), 2)
    tax_total = round(sum(inv["tax"].values()), 2)
    if abs(subtotal - inv["subtotal"]) > tol or abs(tax_total - inv["tax_total"]) > tol \
            or abs(inv["subtotal"] + inv["tax_total"] - inv["total"]) > tol:
        out.append(Finding("ARITHMETIC_MISMATCH", "high", "Invoice totals do not add up",
                           f"Computed subtotal {_inr(subtotal)} and tax {_inr(tax_total)}, invoice states {_inr(inv['subtotal'])}, {_inr(inv['tax_total'])} and total {_inr(inv['total'])}.",
                           {"computed_subtotal": subtotal, "computed_tax": tax_total, "stated_total": inv["total"]}))
    return out


def check_gst(inv: dict, vendor: dict, company: dict, rules: dict) -> list[Finding]:
    out = []
    tol = rules["tolerances"]["rounding_tolerance_inr"]
    gstin = vendor.get("gstin") or ""
    if not GSTIN_RE.match(gstin) or gstin[:2] != vendor["state_code"]:
        out.append(Finding("GSTIN_INVALID", "medium", "Vendor GSTIN looks invalid",
                           f"GSTIN {gstin or 'missing'} does not match the expected format or state code {vendor['state_code']}.",
                           {"gstin": gstin}))
    for ln in inv["lines"]:
        if ln["gst_rate"] not in rules["gst_rates"]:
            out.append(Finding("GST_RATE_INVALID", "high", "Unsupported GST rate",
                               f"{ln['description']} is billed at {ln['gst_rate']}%, which is not a valid GST slab.",
                               {"item_code": ln["item_code"], "rate": ln["gst_rate"]}))
    intra = vendor["state_code"] == company["state_code"]
    expected_tax = round(sum(ln["amount"] * ln["gst_rate"] / 100 for ln in inv["lines"]), 2)
    tax = inv["tax"]
    if intra and tax["igst"] > 0:
        out.append(Finding("GST_MISMATCH", "high", "IGST charged on an intra-state supply",
                           f"Vendor and buyer are both in state {company['state_code']} ({company['state']}), so CGST plus SGST is due, "
                           f"but the invoice charges IGST of {_inr(tax['igst'])}. Input tax credit would be at risk.",
                           {"expected_head": "CGST+SGST", "charged_head": "IGST", "igst": tax["igst"]}))
    elif not intra and (tax["cgst"] > 0 or tax["sgst"] > 0):
        out.append(Finding("GST_MISMATCH", "high", "CGST and SGST charged on an inter-state supply",
                           f"Vendor state {vendor['state_code']} differs from buyer state {company['state_code']}, so IGST is due.",
                           {"expected_head": "IGST", "charged_head": "CGST+SGST"}))
    elif abs(expected_tax - inv["tax_total"]) > tol:
        out.append(Finding("GST_MISMATCH", "medium", "GST amount differs from line rates",
                           f"Line rates give {_inr(expected_tax)} of GST, invoice charges {_inr(inv['tax_total'])}.",
                           {"expected_tax": expected_tax, "stated_tax": inv["tax_total"]}))
    return out


def check_po(inv: dict, vendor: dict, store: DataStore, rules: dict) -> tuple[list[Finding], list[dict]]:
    out: list[Finding] = []
    rows: list[dict] = []
    if not inv.get("po_id"):
        sev = "medium" if vendor["supply_type"] == "services" else "high"
        out.append(Finding("MISSING_PO", sev, "No purchase order referenced",
                           "Invoice does not quote a PO number, so there is nothing to match price or quantity against. "
                           "It needs approval from the cost centre owner.", {}))
        return out, rows
    po = store.get_purchase_order(inv["po_id"])
    if not po:
        out.append(Finding("PO_NOT_FOUND", "high", "Referenced PO does not exist",
                           f"PO {inv['po_id']} is not in the purchasing system.", {"po_id": inv["po_id"]}))
        return out, rows
    if po["vendor_id"] != inv["vendor_id"]:
        out.append(Finding("PO_VENDOR_MISMATCH", "high", "PO belongs to a different vendor",
                           f"PO {po['id']} was raised on vendor {po['vendor_id']}.", {"po_id": po["id"]}))

    grn = store.get_goods_receipt(inv.get("grn_id"))
    received = {ln["item_code"]: ln["qty_received"] for ln in grn["lines"]} if grn else {}
    tol_pct = rules["tolerances"]["price_variance_pct"]
    po_lines = {ln["item_code"]: ln for ln in po["lines"]}
    prior = [i for i in store.paid_invoices_for_po(po["id"]) if i["id"] != inv["id"]]

    for ln in inv["lines"]:
        pl = po_lines.get(ln["item_code"])
        if not pl:
            out.append(Finding("ITEM_NOT_ON_PO", "high", "Invoiced item is not on the PO",
                               f"{ln['description']} does not appear on PO {po['id']}.", {"item_code": ln["item_code"]}))
            continue
        prev_qty = sum(x["qty"] for i in prior for x in i["lines"] if x["item_code"] == ln["item_code"])
        remaining = pl["qty"] - prev_qty
        variance = round((ln["unit_price"] - pl["unit_price"]) / pl["unit_price"] * 100, 2)
        row = {
            "item_code": ln["item_code"], "description": ln["description"], "unit": ln["unit"],
            "po_qty": pl["qty"], "previously_invoiced": prev_qty, "remaining_qty": remaining,
            "invoiced_qty": ln["qty"], "received_qty": received.get(ln["item_code"]) if grn else None,
            "po_price": pl["unit_price"], "invoiced_price": ln["unit_price"], "price_variance_pct": variance,
            "qty_ok": ln["qty"] <= remaining, "price_ok": abs(variance) <= tol_pct,
        }
        rows.append(row)
        if abs(variance) > tol_pct:
            out.append(Finding("PRICE_VARIANCE", "high" if abs(variance) > 5 else "medium",
                               "Unit price differs from PO",
                               f"{ln['description']} billed at {_inr(ln['unit_price'])} per {ln['unit']} against PO rate "
                               f"{_inr(pl['unit_price'])}, a {variance:+.2f}% variance (tolerance {tol_pct}%). "
                               f"Extra cost {_inr((ln['unit_price'] - pl['unit_price']) * ln['qty'])} before tax.",
                               {"item_code": ln["item_code"], "po_price": pl["unit_price"], "invoiced_price": ln["unit_price"],
                                "variance_pct": variance}))
        if ln["qty"] > remaining:
            detail = (f"{ln['qty']} {ln['unit']} invoiced but PO {po['id']} allows {pl['qty']}"
                      + (f" and {prev_qty} were already invoiced" if prev_qty else "") + f", leaving {remaining}.")
            out.append(Finding("QTY_EXCEEDS_PO", "high", "Invoiced quantity exceeds PO", detail,
                               {"item_code": ln["item_code"], "po_qty": pl["qty"], "previously_invoiced": prev_qty,
                                "invoiced_qty": ln["qty"]}))
    return out, rows


def check_grn(inv: dict, vendor: dict, store: DataStore) -> list[Finding]:
    if vendor["supply_type"] == "services" or not inv.get("po_id"):
        return []
    grn = store.get_goods_receipt(inv.get("grn_id"))
    if not grn:
        return [Finding("NO_GOODS_RECEIPT", "medium", "No goods receipt recorded",
                        "Stores has not booked a GRN against this PO, so delivery is unconfirmed.", {})]
    out = []
    received = {ln["item_code"]: ln["qty_received"] for ln in grn["lines"]}
    for ln in inv["lines"]:
        got = received.get(ln["item_code"], 0)
        if ln["qty"] > got:
            out.append(Finding("QTY_EXCEEDS_RECEIPT", "high", "Invoiced quantity exceeds goods received",
                               f"{ln['qty']} {ln['unit']} of {ln['description']} invoiced, GRN {grn['id']} records {got} received.",
                               {"item_code": ln["item_code"], "invoiced_qty": ln["qty"], "received_qty": got, "grn_id": grn["id"]}))
    return out


def normalize_invoice_no(no: str) -> str:
    s = re.sub(r"\s+", "", no.upper())
    return RESUBMIT_SUFFIX_RE.sub("", s)


def check_duplicate(inv: dict, store: DataStore, rules: dict) -> list[Finding]:
    tol = rules["tolerances"]
    norm = normalize_invoice_no(inv["invoice_no"])
    for other in store.invoices.values():
        if other["id"] == inv["id"] or other["vendor_id"] != inv["vendor_id"]:
            continue
        same_no = other["invoice_no"].upper() == inv["invoice_no"].upper()
        same_norm = normalize_invoice_no(other["invoice_no"]) == norm
        close_amount = abs(other["total"] - inv["total"]) <= inv["total"] * tol["duplicate_amount_pct"] / 100
        close_date = abs((_d(other["invoice_date"]) - _d(inv["invoice_date"])).days) <= tol["duplicate_window_days"]
        same_po = bool(inv.get("po_id")) and other.get("po_id") == inv.get("po_id")
        if same_no or same_norm or (close_amount and close_date and same_po):
            basis = "identical invoice number" if same_no else (
                "same invoice number apart from a resubmission suffix" if same_norm else "same PO, amount and date window")
            return [Finding("DUPLICATE_SUSPECTED", "high", "Possible duplicate invoice",
                            f"Matches {other['invoice_no']} ({_inr(other['total'])}, dated {other['invoice_date']}, "
                            f"status {other['status']}{', paid on ' + other['paid_on'] if other.get('paid_on') else ''}) on {basis}.",
                            {"matched_invoice_id": other["id"], "matched_invoice_no": other["invoice_no"],
                             "matched_status": other["status"], "matched_paid_on": other.get("paid_on"), "basis": basis})]
    return []


def vendor_baseline(inv: dict, store: DataStore, rules: dict) -> dict:
    inv_date = _d(inv["invoice_date"])
    window_start = inv_date - timedelta(days=183)
    history = [i for i in store.paid_invoices_for_vendor(inv["vendor_id"])
               if window_start <= _d(i["invoice_date"]) < inv_date]
    totals = [i["total"] for i in history]
    base = {
        "invoice_count": len(totals),
        "window_days": 183,
        "recent": [{"invoice_no": i["invoice_no"], "invoice_date": i["invoice_date"], "total": i["total"]} for i in history],
        "median": None, "min": None, "max": None, "ratio": None,
    }
    if len(totals) >= rules["tolerances"]["baseline_min_invoices"]:
        med = statistics.median(totals)
        base.update(median=round(med, 2), min=min(totals), max=max(totals), ratio=round(inv["total"] / med, 2))
    return base


def check_amount_pattern(inv: dict, baseline: dict, rules: dict) -> list[Finding]:
    tol = rules["tolerances"]
    if baseline["ratio"] is None:
        return [Finding("INSUFFICIENT_HISTORY", "info", "Not enough vendor history for a baseline",
                        f"Only {baseline['invoice_count']} paid invoices in the last 6 months, "
                        f"at least {tol['baseline_min_invoices']} are needed.", {"invoice_count": baseline["invoice_count"]})]
    if baseline["ratio"] >= tol["amount_spike_ratio"]:
        return [Finding("AMOUNT_SPIKE", "medium", "Unusually high invoice amount for this vendor",
                        f"Total {_inr(inv['total'])} is {baseline['ratio']}x the vendor's 6-month median of {_inr(baseline['median'])} "
                        f"(range {_inr(baseline['min'])} to {_inr(baseline['max'])} over {baseline['invoice_count']} invoices).",
                        {"ratio": baseline["ratio"], "median": baseline["median"]})]
    if baseline["ratio"] <= tol["amount_low_ratio"]:
        return [Finding("AMOUNT_LOW", "low", "Unusually low invoice amount for this vendor",
                        f"Total {_inr(inv['total'])} is {baseline['ratio']}x the vendor's 6-month median of {_inr(baseline['median'])}. "
                        "Could be a partial delivery, a split invoice or a missing line.",
                        {"ratio": baseline["ratio"], "median": baseline["median"]})]
    return []


def check_vendor(inv: dict, vendor: dict, rules: dict) -> list[Finding]:
    out = []
    age = (_d(inv["invoice_date"]) - _d(vendor["onboarded_on"])).days
    if age < rules["tolerances"]["new_vendor_days"]:
        out.append(Finding("NEW_VENDOR", "medium", "New vendor",
                           f"{vendor['name']} was onboarded on {vendor['onboarded_on']}, {age} days before this invoice. "
                           "No payment history to compare against.", {"vendor_age_days": age}))
    if inv.get("bank_account_last4") and inv["bank_account_last4"] != vendor["bank"]["account_last4"]:
        out.append(Finding("BANK_DETAILS_CHANGED", "high", "Bank account differs from vendor master",
                           f"Invoice asks for payment to account ending {inv['bank_account_last4']}, vendor master has "
                           f"{vendor['bank']['bank_name']} account ending {vendor['bank']['account_last4']}. "
                           "Bank detail changes on invoices are the most common payment diversion fraud pattern.",
                           {"invoice_account_last4": inv["bank_account_last4"],
                            "master_account_last4": vendor["bank"]["account_last4"]}))
    return out


def payment_schedule(inv: dict, vendor: dict, rules: dict) -> tuple[list[Finding], dict]:
    out = []
    inv_date = _d(inv["invoice_date"])
    stated_terms = inv["payment_terms"]
    master_terms = vendor["payment_terms"]
    if stated_terms != master_terms:
        out.append(Finding("TERMS_MISMATCH", "low", "Payment terms differ from vendor master",
                           f"Invoice states {stated_terms}, vendor master says {master_terms}. Master terms apply.",
                           {"invoice_terms": stated_terms, "master_terms": master_terms}))
    expected_due = inv_date + timedelta(days=TERMS_DAYS[stated_terms])
    if inv.get("due_date") and _d(inv["due_date"]) != expected_due:
        out.append(Finding("DUE_DATE_MISMATCH", "low", "Due date does not follow the stated terms",
                           f"{stated_terms} from {inv['invoice_date']} gives {expected_due.isoformat()}, invoice shows {inv['due_date']}.",
                           {"expected": expected_due.isoformat(), "stated": inv["due_date"]}))
    days = TERMS_DAYS[master_terms]
    cap = rules["msme_max_payment_days"]
    if vendor.get("msme"):
        stated_days = (_d(inv["due_date"]) - inv_date).days if inv.get("due_date") else days
        if stated_days > cap:
            out.append(Finding("MSME_45_DAY_BREACH", "medium", "MSME vendor must be paid within 45 days",
                               f"{vendor['name']} is MSME registered ({vendor['udyam_no']}). The MSMED Act caps payment at "
                               f"{cap} days, and late payments lose the tax deduction under section 43B(h). "
                               f"Invoice terms allow {stated_days} days.", {"stated_days": stated_days, "cap_days": cap}))
        days = min(days, cap)
    pay_by = inv_date + timedelta(days=days)
    return out, {"master_terms": master_terms, "invoice_terms": stated_terms, "msme": vendor.get("msme", False),
                 "pay_by": pay_by.isoformat(), "days": days}


def approval_requirement(inv: dict, findings: list[Finding], rules: dict) -> dict:
    tiers = rules["tiers"]
    base = next(t for t in tiers if t["max_amount"] is None or inv["total"] <= t["max_amount"])
    level, reasons = base["level"], [f"Amount {_inr(inv['total'])} falls in the {base['approver_role']} band"]
    codes = {f.code for f in findings}
    triggers = {
        "new_vendor": "NEW_VENDOR" in codes,
        "high_severity_finding": any(f.severity == "high" for f in findings),
        "bank_details_changed": "BANK_DETAILS_CHANGED" in codes,
        "missing_po": "MISSING_PO" in codes,
    }
    for esc in rules["escalations"]:
        if triggers.get(esc["when"]) and esc["min_level"] > level:
            level = esc["min_level"]
            reasons.append(esc["reason"])
        elif triggers.get(esc["when"]):
            reasons.append(esc["reason"])
    role = next(t["approver_role"] for t in tiers if t["level"] == level)
    return {"level": level, "approver_role": role, "base_role": base["approver_role"], "reasons": reasons}


# ---------------------------------------------------------------- orchestration


def run_checks(store: DataStore, invoice_id: str) -> dict:
    inv = store.get_invoice(invoice_id)
    if not inv:
        raise KeyError(invoice_id)
    vendor = store.get_vendor(inv["vendor_id"])
    rules = store.approval_rules
    tol = rules["tolerances"]["rounding_tolerance_inr"]

    findings: list[Finding] = []
    findings += check_arithmetic(inv, tol)
    findings += check_gst(inv, vendor, store.company, rules)
    po_findings, po_rows = check_po(inv, vendor, store, rules)
    findings += po_findings
    findings += check_grn(inv, vendor, store)
    findings += check_duplicate(inv, store, rules)
    baseline = vendor_baseline(inv, store, rules)
    findings += check_amount_pattern(inv, baseline, rules)
    findings += check_vendor(inv, vendor, rules)
    pay_findings, payment = payment_schedule(inv, vendor, rules)
    findings += pay_findings

    approval = approval_requirement(inv, findings, rules)
    if approval["base_role"] == "CFO":
        findings.append(Finding("APPROVAL_CFO", "low", "Requires CFO approval",
                                "; ".join(approval["reasons"]) + ".", {"level": 3}))

    findings.sort(key=lambda f: -SEVERITY_ORDER[f.severity])
    exceptions = [f for f in findings if f.severity != "info"]
    max_sev = exceptions[0].severity if exceptions else "none"
    po = store.get_purchase_order(inv.get("po_id"))
    return {
        "invoice": inv,
        "vendor": vendor,
        "purchase_order": po,
        "goods_receipt": store.get_goods_receipt(inv.get("grn_id")),
        "po_comparison": po_rows,
        "findings": [asdict(f) for f in findings],
        "exception_codes": sorted({f.code for f in exceptions}),
        "status": "exception" if exceptions else "clean",
        "max_severity": max_sev,
        "baseline": baseline,
        "payment": payment,
        "approval": approval,
    }
