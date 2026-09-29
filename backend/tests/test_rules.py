"""Deterministic AP rule tests. No network, no LLM."""

import copy

import pytest

from app.data_store import DataStore
from app.rules import _inr, normalize_invoice_no, run_checks


@pytest.fixture(scope="module")
def store():
    return DataStore()


def codes(store, invoice_id):
    return set(run_checks(store, invoice_id)["exception_codes"])


def test_normal_invoice_is_clean(store):
    r = run_checks(store, "INV-2004")
    assert r["status"] == "clean"
    assert r["exception_codes"] == []
    assert r["approval"]["approver_role"] == "AP Executive"
    assert all(row["qty_ok"] and row["price_ok"] for row in r["po_comparison"])


def test_price_discrepancy(store):
    r = run_checks(store, "INV-2005")
    assert "PRICE_VARIANCE" in r["exception_codes"]
    f = next(f for f in r["findings"] if f["code"] == "PRICE_VARIANCE")
    assert f["evidence"]["variance_pct"] == pytest.approx(4.2, abs=0.01)
    assert f["severity"] == "medium"  # within 5%, so not high


def test_quantity_discrepancy_against_po_and_grn(store):
    c = codes(store, "INV-2003")
    assert {"QTY_EXCEEDS_PO", "QTY_EXCEEDS_RECEIPT", "AMOUNT_SPIKE"} <= c


def test_amended_po_quantity_is_accepted(store):
    # INV-2001 bills 2,000 boxes against a PO amended to 2,000: only the amount spike remains.
    assert codes(store, "INV-2001") == {"AMOUNT_SPIKE"}


def test_duplicate_with_resubmission_suffix(store):
    r = run_checks(store, "INV-2006")
    dup = next(f for f in r["findings"] if f["code"] == "DUPLICATE_SUSPECTED")
    assert dup["evidence"]["matched_invoice_no"] == "MPL/26-27/1187"
    assert dup["evidence"]["matched_status"] == "paid"
    assert normalize_invoice_no("MPL/26-27/1187/R1") == normalize_invoice_no("MPL/26-27/1187")


def test_missing_po(store):
    r = run_checks(store, "INV-2008")
    assert "MISSING_PO" in r["exception_codes"]
    assert r["approval"]["level"] >= 2


def test_approval_threshold_cfo(store):
    r = run_checks(store, "INV-2009")
    assert r["approval"]["approver_role"] == "CFO"
    assert r["exception_codes"] == ["APPROVAL_CFO"]


def test_approval_tiers(store):
    assert run_checks(store, "INV-2002")["approval"]["approver_role"] == "AP Executive"   # 90,860
    assert run_checks(store, "INV-2005")["approval"]["approver_role"] == "Finance Manager"  # 1,63,878.40


def test_gst_head_mismatch_intra_state(store):
    r = run_checks(store, "INV-2007")
    f = next(f for f in r["findings"] if f["code"] == "GST_MISMATCH")
    assert f["evidence"]["expected_head"] == "CGST+SGST"
    assert f["severity"] == "high"


def test_new_msme_vendor_terms(store):
    c = codes(store, "INV-2010")
    assert {"NEW_VENDOR", "MSME_45_DAY_BREACH", "TERMS_MISMATCH"} <= c
    r = run_checks(store, "INV-2010")
    assert r["payment"]["days"] == 30  # master NET30, already under the 45 day cap


def test_bank_details_changed_escalates_to_cfo(store):
    r = run_checks(store, "INV-2011")
    assert "BANK_DETAILS_CHANGED" in r["exception_codes"]
    assert r["approval"]["level"] == 3
    assert "APPROVAL_CFO" not in r["exception_codes"]  # CFO flag is only for the amount band


def test_unusually_low_amount(store):
    assert "AMOUNT_LOW" in codes(store, "INV-2012")


def test_arithmetic_mismatch_detected(store):
    s = copy.deepcopy(store)
    s.invoices["INV-2004"]["total"] += 500
    assert "ARITHMETIC_MISMATCH" in set(run_checks(s, "INV-2004")["exception_codes"])


def test_dataset_totals_are_consistent(store):
    for inv in store.invoices.values():
        assert "ARITHMETIC_MISMATCH" not in set(run_checks(store, inv["id"])["exception_codes"]), inv["id"]


def test_indian_number_format():
    assert _inr(682500) == "Rs 6,82,500"
    assert _inr(163878.4) == "Rs 1,63,878.40"
    assert _inr(999) == "Rs 999"
