"""Hindsight integration: the agent's long-term memory of resolved exceptions.

All Hindsight calls live in this module. Resolutions are retained as narrative
text plus structured metadata and tags. Recall runs two tag-scoped passes (same
vendor, same exception type) and code, not the LLM, decides whether anything
retrieved counts as a precedent.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from hindsight_client import Hindsight

from .config import Settings

log = logging.getLogger("precedent.memory")

RETAIN_MISSION = (
    "This bank is the institutional memory of an accounts payable team. Extract, for each resolved invoice "
    "exception: the vendor, the invoice number and amount, which exception was raised, the evidence the reviewer "
    "checked, the decision (approve, approve with conditions, hold, reject), who decided and when, the reason, and "
    "any conditions or standing instructions. Keep amounts, invoice numbers, PO numbers and dates exact."
)
OBSERVATIONS_MISSION = (
    "Observations are durable patterns about vendors and exception types: how a vendor typically invoices, which "
    "exceptions recur, what evidence made past exceptions legitimate, and which situations were fraud or errors. "
    "Ignore one-off details that do not generalise."
)
REFLECT_MISSION = (
    "You advise an accounts payable reviewer. Be skeptical: past approvals never justify skipping verification of "
    "the current invoice. Cite the specific past cases you rely on and say when a past case does not apply."
)

RELATION_LABELS = {
    "same_vendor_same_issue": "Same vendor, same exception",
    "same_issue_other_vendor": "Same exception, different vendor",
    "same_vendor_other_issue": "Same vendor, different exception",
}


def vendor_tag(vendor_id: str) -> str:
    return f"vendor:{vendor_id}"


def exc_tag(code: str) -> str:
    return f"exc:{code}"


def case_content(case: dict) -> str:
    """Narrative text Hindsight extracts facts from. Written like a reviewer's case note."""
    lines = [
        f"Accounts payable exception case {case['case_id']}.",
        f"Vendor: {case['vendor_name']} (vendor id {case['vendor_id']}).",
        f"Invoice {case['invoice_no']} dated {case['invoice_date']} for Rs {case['total']:,.2f}.",
    ]
    if case.get("findings_text"):
        lines.append(f"Exceptions raised by the rule checks: {case['findings_text']}")
    elif case.get("summary"):
        lines.append(f"Exception: {case['summary']}")
    if case.get("facts"):
        lines.append("Facts at the time of review: " + " ".join(case["facts"]))
    decision = case["decision"].replace("_", " ")
    lines.append(f"Decision: {decision.upper()} by reviewer {case['reviewer']} on {case['resolved_on']}.")
    lines.append(f"Reason given by the reviewer: {case['reason']}")
    if case.get("evidence"):
        lines.append("Evidence the reviewer checked: " + "; ".join(case["evidence"]) + ".")
    if case.get("conditions"):
        lines.append("Conditions or standing instructions: " + "; ".join(case["conditions"]) + ".")
    return "\n".join(lines)


def case_metadata(case: dict) -> dict[str, str]:
    return {
        "case_id": case["case_id"],
        "invoice_id": case.get("invoice_id") or "",
        "invoice_no": case["invoice_no"],
        "vendor_id": case["vendor_id"],
        "vendor_name": case["vendor_name"],
        "exception_codes": ",".join(case["exception_codes"]),
        "decision": case["decision"],
        "reviewer": case["reviewer"],
        "resolved_on": case["resolved_on"],
        "total": f"{case['total']:.2f}",
        "source": case.get("source", "reviewer"),
    }


def case_tags(case: dict) -> list[str]:
    return [vendor_tag(case["vendor_id"]), *(exc_tag(c) for c in case["exception_codes"]),
            f"decision:{case['decision']}", f"reviewer:{case['reviewer'].lower().replace(' ', '-')}"]


def _ts(date_str: str) -> datetime:
    """Resolution dates become the memory timestamp so temporal recall works."""
    try:
        d = datetime.fromisoformat(date_str)
    except ValueError:
        return datetime.now(timezone.utc)
    return d if d.tzinfo else d.replace(hour=12, tzinfo=timezone.utc)


class MemoryService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bank_id = settings.hindsight_bank_id
        self.client = Hindsight(base_url=settings.hindsight_base_url,
                                api_key=settings.hindsight_api_key or None, timeout=180.0)
        self._bank_ready = False
        self._lock = asyncio.Lock()

    async def ensure_bank(self) -> None:
        if self._bank_ready:
            return
        async with self._lock:
            if self._bank_ready:
                return
            await self.client.acreate_bank(
                self.bank_id,
                retain_mission=RETAIN_MISSION,
                observations_mission=OBSERVATIONS_MISSION,
                reflect_mission=REFLECT_MISSION,
                enable_observations=True,
            )
            self._bank_ready = True
            log.info("[hindsight] bank ready: %s", self.bank_id)

    # ------------------------------------------------------------------ retain

    async def retain_case(self, case: dict) -> dict:
        await self.ensure_bank()
        t0 = time.perf_counter()
        content = case_content(case)
        resp = await self.client.aretain(
            bank_id=self.bank_id,
            content=content,
            context="Accounts payable exception resolution recorded by a human reviewer",
            timestamp=_ts(case["resolved_on"]),
            document_id=case["case_id"],
            metadata=case_metadata(case),
            tags=case_tags(case),
        )
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("[hindsight] retain %s tags=%s in %dms", case["case_id"], case_tags(case), ms)
        return {"case_id": case["case_id"], "document_id": case["case_id"], "bank_id": self.bank_id,
                "tags": case_tags(case), "content": content, "elapsed_ms": ms,
                "success": bool(getattr(resp, "success", True))}

    async def retain_cases(self, cases: list[dict]) -> dict:
        await self.ensure_bank()
        t0 = time.perf_counter()
        items = [{
            "content": case_content(c),
            "context": "Accounts payable exception resolution recorded by a human reviewer",
            "timestamp": _ts(c["resolved_on"]),
            "document_id": c["case_id"],
            "metadata": case_metadata(c),
            "tags": case_tags(c),
        } for c in cases]
        await self.client.aretain_batch(bank_id=self.bank_id, items=items)
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("[hindsight] retain_batch %d cases in %dms", len(cases), ms)
        return {"retained": [c["case_id"] for c in cases], "elapsed_ms": ms, "bank_id": self.bank_id}

    # ------------------------------------------------------------------ recall

    @staticmethod
    def build_query(analysis: dict) -> str:
        inv, vendor = analysis["invoice"], analysis["vendor"]
        issues = [f for f in analysis["findings"] if f["severity"] != "info"]
        issue_text = "; ".join(f"{f['title']}: {f['detail']}" for f in issues[:4]) or "no exceptions"
        q = (f"Past resolved exceptions for {vendor['name']} or similar invoices. Current invoice {inv['invoice_no']} "
             f"for Rs {inv['total']:,.2f}. Issues: {issue_text}")
        return q[:1500]

    async def _recall(self, query: str, tags: list[str]) -> list:
        resp = await self.client.arecall(bank_id=self.bank_id, query=query, tags=tags,
                                         tags_match="any_strict", budget="mid", max_tokens=4096)
        return list(resp.results or [])

    async def recall_precedents(self, analysis: dict, extra_query: str | None = None) -> dict:
        """Two tag-scoped recall passes, then deterministic gating into precedent cases."""
        await self.ensure_bank()
        inv, vendor = analysis["invoice"], analysis["vendor"]
        codes = analysis["exception_codes"]
        query = extra_query or self.build_query(analysis)
        passes = [("vendor", [vendor_tag(vendor["id"])])]
        if codes:
            passes.append(("exception", [exc_tag(c) for c in codes]))

        t0 = time.perf_counter()
        results = await asyncio.gather(*(self._recall(query, tags) for _, tags in passes), return_exceptions=True)
        ms = int((time.perf_counter() - t0) * 1000)

        errors, raw = [], []
        for (name, tags), res in zip(passes, results):
            if isinstance(res, Exception):
                errors.append(f"{name} pass failed: {res}")
                continue
            for r in res:
                raw.append((name, r))
            log.info("[hindsight] recall pass=%s tags=%s -> %d results", name, tags, len(res))

        cases: dict[str, dict] = {}
        patterns: dict[str, dict] = {}
        seen_facts: set[str] = set()
        for pass_name, r in raw:
            if r.id in seen_facts:
                continue
            seen_facts.add(r.id)
            if r.type == "observation":
                patterns[r.id] = {"id": r.id, "text": r.text, "tags": r.tags or [], "pass": pass_name}
                continue
            md = r.metadata or {}
            case_id = md.get("case_id") or r.document_id
            if not case_id:
                continue
            c = cases.setdefault(case_id, {"case_id": case_id, "metadata": md, "facts": [], "tags": set(),
                                           "passes": set(), "occurred": r.occurred_start or r.mentioned_at})
            if md and not c["metadata"]:
                c["metadata"] = md
            c["facts"].append(r.text)
            c["tags"].update(r.tags or [])
            c["passes"].add(pass_name)

        precedents, context_cases, gated_out = [], [], []
        current_codes = set(codes)
        for c in cases.values():
            md = c["metadata"]
            c_vendor = md.get("vendor_id") or next((t.split(":", 1)[1] for t in c["tags"] if t.startswith("vendor:")), "")
            c_codes = set(filter(None, (md.get("exception_codes") or "").split(","))) or \
                {t.split(":", 1)[1] for t in c["tags"] if t.startswith("exc:")}
            shared = sorted(current_codes & c_codes)
            entry = {
                "case_id": c["case_id"],
                "invoice_no": md.get("invoice_no"),
                "vendor_id": c_vendor,
                "vendor_name": md.get("vendor_name"),
                "decision": md.get("decision"),
                "reviewer": md.get("reviewer"),
                "resolved_on": md.get("resolved_on"),
                "total": md.get("total"),
                "exception_codes": sorted(c_codes),
                "shared_codes": shared,
                "facts": c["facts"][:8],
                "matched_by": sorted(c["passes"]),
            }
            if md.get("invoice_id") and md.get("invoice_id") == inv["id"]:
                gated_out.append({**entry, "gate_reason": "This is the current invoice's own earlier resolution"})
            elif c_vendor == vendor["id"] and shared:
                precedents.append({**entry, "relation": "same_vendor_same_issue"})
            elif shared:
                precedents.append({**entry, "relation": "same_issue_other_vendor"})
            elif c_vendor == vendor["id"]:
                context_cases.append({**entry, "relation": "same_vendor_other_issue"})
            else:
                gated_out.append({**entry, "gate_reason": "Different vendor and no shared exception type"})

        order = {"same_vendor_same_issue": 0, "same_issue_other_vendor": 1}
        precedents.sort(key=lambda p: (order[p["relation"]], p.get("resolved_on") or ""), reverse=False)
        for p in precedents + context_cases:
            p["relation_label"] = RELATION_LABELS[p["relation"]]
        n = len(precedents)
        status = "none" if n == 0 else ("single" if n == 1 else "multiple")
        return {
            "enabled": True,
            "bank_id": self.bank_id,
            "status": status,
            "precedent_count": n,
            "precedents": precedents,
            "vendor_context": context_cases,
            "patterns": list(patterns.values())[:5],
            "gated_out": gated_out,
            "raw_result_count": len(raw),
            "query": query,
            "passes": [{"name": n_, "tags": t} for n_, t in passes],
            "elapsed_ms": ms,
            "errors": errors,
        }

    # ------------------------------------------------------------------ reflect, admin

    async def reflect(self, question: str, tags: list[str] | None = None) -> dict:
        await self.ensure_bank()
        t0 = time.perf_counter()
        resp = await self.client.areflect(bank_id=self.bank_id, query=question, budget="mid",
                                          tags=tags, tags_match="any_strict" if tags else "any")
        return {"answer": resp.text, "elapsed_ms": int((time.perf_counter() - t0) * 1000)}

    async def stats(self) -> dict:
        await self.ensure_bank()
        resp = await self.client.alist_memories(bank_id=self.bank_id, limit=1)
        return {"bank_id": self.bank_id, "memory_units": resp.total}

    async def reset(self) -> dict:
        try:
            await self.client.banks.delete_bank(self.bank_id)
        except Exception as e:  # deleting a bank that does not exist yet is fine
            if "404" not in str(e):
                raise
        self._bank_ready = False
        await self.ensure_bank()
        log.info("[hindsight] bank reset: %s", self.bank_id)
        return {"bank_id": self.bank_id, "reset": True}
