"""Memory gating and guardrail tests. Hindsight is stubbed, so these run offline."""

import asyncio
from types import SimpleNamespace

from app.agent import Agent, _clean
from app.config import Settings
from app.data_store import DataStore
from app.memory import MemoryService
from app.rules import run_checks

SETTINGS = Settings(groq_api_key="", groq_model="x", hindsight_base_url="http://localhost:8888",
                    hindsight_api_key="", hindsight_bank_id="test", cors_origins=[])


def fact(fid, text, case=None, vendor=None, codes="", decision="approve", invoice_id="", kind=None, note_id=None,
         reviewer="", ftype="world"):
    if kind:
        md = {"kind": kind, "note_id": note_id, "vendor_id": vendor or "", "reviewer": reviewer, "author": "t",
              "created_on": "2026-09-01"}
    else:
        md = {"case_id": case, "vendor_id": vendor, "exception_codes": codes, "decision": decision,
              "invoice_id": invoice_id, "invoice_no": case, "vendor_name": vendor, "reviewer": "Priya Nair",
              "resolved_on": "2026-09-01T10:00:00+00:00"}
    return SimpleNamespace(id=fid, text=text, type=ftype, metadata=md, document_id=note_id or case, tags=[],
                           occurred_start=None, mentioned_at=None)


class StubClient:
    def __init__(self, results):
        self.results = results

    async def arecall(self, **kwargs):
        return SimpleNamespace(results=self.results)


def recall(results, invoice_id="INV-2001", reviewer=None):
    store = DataStore()
    svc = MemoryService(SETTINGS)
    svc.client = StubClient(results)
    svc._bank_ready = True
    return asyncio.run(svc.recall_precedents(run_checks(store, invoice_id), reviewer=reviewer))


def test_no_results_means_no_precedent():
    m = recall([])
    assert m["status"] == "none" and m["precedent_count"] == 0


def test_gating_classifies_relations():
    m = recall([
        fact("f1", "a", case="CASE-A", vendor="V001", codes="AMOUNT_SPIKE"),          # same vendor, same issue
        fact("f2", "b", case="CASE-B", vendor="V009", codes="AMOUNT_SPIKE"),          # other vendor, same issue
        fact("f3", "c", case="CASE-C", vendor="V001", codes="GST_MISMATCH"),          # same vendor, other issue
        fact("f4", "d", case="CASE-D", vendor="V005", codes="MISSING_PO"),            # unrelated
        fact("f5", "e", case="CASE-SELF", vendor="V001", codes="AMOUNT_SPIKE", invoice_id="INV-2001"),
    ])
    rel = {p["case_id"]: p["relation"] for p in m["precedents"]}
    assert rel == {"CASE-A": "same_vendor_same_issue", "CASE-B": "same_issue_other_vendor"}
    assert [c["case_id"] for c in m["vendor_context"]] == ["CASE-C"]
    gated = {g["case_id"] for g in m["gated_out"]}
    assert gated == {"CASE-D", "CASE-SELF"}
    assert m["status"] == "multiple"


def test_facts_from_one_case_are_grouped():
    m = recall([fact("f1", "a", case="CASE-A", vendor="V001", codes="AMOUNT_SPIKE"),
                fact("f2", "b", case="CASE-A", vendor="V001", codes="AMOUNT_SPIKE")])
    assert m["status"] == "single" and len(m["precedents"][0]["facts"]) == 2


def test_strength_levels():
    three = [fact(f"f{i}", "x", case=f"CASE-{i}", vendor="V001", codes="AMOUNT_SPIKE") for i in range(3)]
    assert recall(three)["strength"]["level"] == "established"
    mixed = [fact("f1", "x", case="CASE-1", vendor="V001", codes="AMOUNT_SPIKE", decision="approve"),
             fact("f2", "x", case="CASE-2", vendor="V001", codes="AMOUNT_SPIKE", decision="reject")]
    assert recall(mixed)["strength"]["level"] == "conflicting"


def test_notes_are_routed_and_scoped():
    m = recall([
        fact("n1", "vendor email", kind="vendor_note", note_id="NOTE-1", vendor="V001"),
        fact("n2", "other vendor email", kind="vendor_note", note_id="NOTE-2", vendor="V002"),
        fact("n3", "priya likes grn", kind="reviewer_preference", note_id="NOTE-3", reviewer="Priya Nair"),
        fact("n4", "arjun likes reject", kind="reviewer_preference", note_id="NOTE-4", reviewer="Arjun Menon"),
        fact("n5", "bank policy", kind="policy", note_id="NOTE-5"),
    ], reviewer="Priya Nair")
    assert [n["note_id"] for n in m["vendor_notes"]] == ["NOTE-1"]
    assert [n["note_id"] for n in m["reviewer_preferences"]] == ["NOTE-3"]
    assert [n["note_id"] for n in m["policies"]] == ["NOTE-5"]
    assert m["status"] == "none"  # notes never count as precedents


def test_guardrail_strips_unretrieved_citations():
    out = {"precedent": {"status": "applies", "cases": [{"case_id": "CASE-FAKE", "applies": True, "why": "x"}]},
           "recommendation": {"action": "approve"}}
    warnings = Agent._validate(out, {"enabled": True}, {"retrieved_ids": set()})
    assert out["precedent"]["cases"] == [] and out["precedent"]["status"] == "none"
    assert any("CASE-FAKE" in w for w in warnings)


def test_guardrail_label_follows_case_verdicts():
    out = {"precedent": {"status": "partially_applies", "cases": [{"case_id": "CASE-A", "applies": False, "why": "x"}]},
           "recommendation": {"action": "hold"}}
    Agent._validate(out, {"enabled": True}, {"retrieved_ids": {"CASE-A"}})
    assert out["precedent"]["status"] == "does_not_apply"


def test_guardrail_rejects_unknown_action():
    out = {"precedent": {"status": "none", "cases": []}, "recommendation": {"action": "pay_now"}}
    Agent._validate(out, {"enabled": True}, {"retrieved_ids": set()})
    assert out["recommendation"]["action"] == "hold"


def test_invoice_text_red_flag():
    store = DataStore()
    r = run_checks(store, "INV-2013")
    f = next(f for f in r["findings"] if f["code"] == "INVOICE_TEXT_RED_FLAG")
    assert "claims the invoice is already approved" in f["evidence"]["signals"]
    assert "asks the reviewer to skip a control" in f["evidence"]["signals"]
    assert "INVOICE_TEXT_RED_FLAG" not in run_checks(store, "INV-2006")["exception_codes"]


def test_clean_punctuation_keeps_invoice_numbers():
    assert _clean("trip sheet/delivery challan") == "trip sheet or delivery challan"
    assert _clean("PO/GRN match") == "PO and GRN match"
    assert _clean("invoice SGP/26-27/0412") == "invoice SGP/26-27/0412"
    assert _clean("done — next") == "done, next"
