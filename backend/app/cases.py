"""Turn a human decision into the case record that gets retained in Hindsight."""

from __future__ import annotations

import re

from .rules import review_facts


def case_id_for(invoice_no: str) -> str:
    return "CASE-" + re.sub(r"[^A-Z0-9]+", "-", invoice_no.upper()).strip("-")


def build_case(analysis: dict, *, decision: str, reviewer: str, reason: str, resolved_on: str,
               evidence: list[str] | None = None, conditions: list[str] | None = None,
               source: str = "reviewer", agent_action: str | None = None) -> dict:
    """Facts come from the rule checks, recomputed server side; only the decision and reason come from the person."""
    inv = analysis["invoice"]
    exc = [f for f in analysis["findings"] if f["severity"] != "info"]
    return {
        "case_id": case_id_for(inv["invoice_no"]),
        "invoice_id": inv["id"],
        "invoice_no": inv["invoice_no"],
        "invoice_date": inv["invoice_date"],
        "vendor_id": inv["vendor_id"],
        "vendor_name": analysis["vendor"]["name"],
        "total": inv["total"],
        "exception_codes": analysis["exception_codes"] or ["NONE"],
        "findings_text": " ".join(f"{f['code']}: {f['detail']}" for f in exc) or "No exceptions.",
        "facts": review_facts(analysis),
        "decision": decision,
        "reviewer": reviewer,
        "resolved_on": resolved_on,
        "reason": reason,
        "evidence": evidence or [],
        "conditions": conditions or [],
        "source": source,
        "agent_action": agent_action,
    }
