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
        "agent_action": case.get("agent_action") or "",
    }


def case_tags(case: dict) -> list[str]:
    return [vendor_tag(case["vendor_id"]), *(exc_tag(c) for c in case["exception_codes"]),
            f"decision:{case['decision']}", f"reviewer:{case['reviewer'].lower().replace(' ', '-')}"]


def reviewer_slug(name: str) -> str:
    return name.strip().lower().replace(" ", "-")


NOTE_KINDS = {
    "vendor_note": "Vendor communication",
    "reviewer_preference": "Reviewer preference",
    "policy": "Team policy",
}


def note_content(note: dict) -> str:
    label = NOTE_KINDS[note["kind"]]
    who = f" about vendor {note['vendor_name']} (vendor id {note['vendor_id']})" if note.get("vendor_id") else ""
    rev = f" for reviewer {note['reviewer']}" if note.get("reviewer") else ""
    return f"{label}{who}{rev}, recorded by {note['author']} on {note['created_on']}.\n{note['text']}"


def note_metadata(note: dict) -> dict[str, str]:
    return {"note_id": note["note_id"], "kind": note["kind"], "vendor_id": note.get("vendor_id") or "",
            "vendor_name": note.get("vendor_name") or "", "reviewer": note.get("reviewer") or "",
            "author": note["author"], "created_on": note["created_on"]}


def note_tags(note: dict) -> list[str]:
    tags = [f"kind:{note['kind']}"]
    if note.get("vendor_id"):
        tags.append(vendor_tag(note["vendor_id"]))
    if note.get("reviewer"):
        tags.append(f"reviewer:{reviewer_slug(note['reviewer'])}")
    return tags


# Hindsight mental models: summaries the bank keeps rewriting as resolutions accumulate.
MENTAL_MODELS = [
    {"id": "ap-playbook", "name": "AP Exception Playbook",
     "source_query": "What exception types recur in our accounts payable work, how did reviewers resolve each one, what evidence "
                     "made an exception acceptable or unacceptable, and what standing instructions apply? Organise by exception type "
                     "and cite case ids."},
    {"id": "vendor-watchlist", "name": "Vendor Watchlist",
     "source_query": "Which vendors have a history of exceptions, fraud attempts, tax errors, duplicates or price escalations, and "
                     "what should a reviewer check before paying each of them? One short entry per vendor."},
]


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
            await self._ensure_mental_models()
            self._bank_ready = True
            log.info("[hindsight] bank ready: %s", self.bank_id)

    async def _ensure_mental_models(self) -> None:
        try:
            existing = await self.client.alist_mental_models(bank_id=self.bank_id, detail="metadata")
            have = {m.id for m in existing.items or []}
            for mm in MENTAL_MODELS:
                if mm["id"] not in have:
                    await self.client.acreate_mental_model(bank_id=self.bank_id, id=mm["id"], name=mm["name"],
                                                           source_query=mm["source_query"], max_tokens=1500,
                                                           trigger={"refresh_after_consolidation": True})
                    log.info("[hindsight] mental model created: %s", mm["id"])
        except Exception as e:  # the playbook is a bonus; recall and retain must keep working without it
            log.warning("[hindsight] mental model setup failed: %s", e)

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

    async def retain_note(self, note: dict) -> dict:
        await self.ensure_bank()
        t0 = time.perf_counter()
        content = note_content(note)
        await self.client.aretain(bank_id=self.bank_id, content=content,
                                  context=f"{NOTE_KINDS[note['kind']]} for an accounts payable team",
                                  timestamp=_ts(note["created_on"]), document_id=note["note_id"],
                                  metadata=note_metadata(note), tags=note_tags(note))
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("[hindsight] retain note %s tags=%s in %dms", note["note_id"], note_tags(note), ms)
        return {"note_id": note["note_id"], "tags": note_tags(note), "content": content, "elapsed_ms": ms}

    async def retain_cases(self, cases: list[dict], notes: list[dict] | None = None) -> dict:
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
        items += [{
            "content": note_content(n),
            "context": f"{NOTE_KINDS[n['kind']]} for an accounts payable team",
            "timestamp": _ts(n["created_on"]),
            "document_id": n["note_id"],
            "metadata": note_metadata(n),
            "tags": note_tags(n),
        } for n in notes or []]
        await self.client.aretain_batch(bank_id=self.bank_id, items=items)
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("[hindsight] retain_batch %d cases, %d notes in %dms", len(cases), len(notes or []), ms)
        return {"retained": [c["case_id"] for c in cases] + [n["note_id"] for n in notes or []],
                "elapsed_ms": ms, "bank_id": self.bank_id}

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

    async def recall_precedents(self, analysis: dict, extra_query: str | None = None,
                                reviewer: str | None = None, lite: bool = False) -> dict:
        """Tag-scoped recall passes, then deterministic gating into precedents, notes and preferences."""
        await self.ensure_bank()
        inv, vendor = analysis["invoice"], analysis["vendor"]
        codes = analysis["exception_codes"]
        query = extra_query or self.build_query(analysis)
        passes = [("vendor", [vendor_tag(vendor["id"])])]
        if codes:
            passes.append(("exception", [exc_tag(c) for c in codes]))
        if not lite:
            passes.append(("policy", ["kind:policy"]))
            if reviewer:
                passes.append(("reviewer", [f"reviewer:{reviewer_slug(reviewer)}"]))

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
        notes: dict[str, dict] = {}
        seen_facts: set[str] = set()
        for pass_name, r in raw:
            if r.id in seen_facts:
                continue
            seen_facts.add(r.id)
            if r.type == "observation":
                patterns[r.id] = {"id": r.id, "text": r.text, "tags": r.tags or [], "pass": pass_name}
                continue
            md = r.metadata or {}
            if md.get("kind") in NOTE_KINDS:
                kind = md["kind"]
                relevant = (kind == "policy"
                            or (kind == "vendor_note" and md.get("vendor_id") == vendor["id"])
                            or (kind == "reviewer_preference" and bool(reviewer)
                                and md.get("reviewer", "").lower() == (reviewer or "").lower()))
                if relevant:
                    n = notes.setdefault(md["note_id"], {"note_id": md["note_id"], "kind": kind, "label": NOTE_KINDS[kind],
                                                        "author": md.get("author"), "created_on": md.get("created_on"),
                                                        "reviewer": md.get("reviewer"), "facts": []})
                    if len(n["facts"]) < 4:
                        n["facts"].append(r.text)
                continue
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
        now = datetime.now(timezone.utc)
        for p in precedents + context_cases:
            p["relation_label"] = RELATION_LABELS[p["relation"]]
            try:
                p["age_days"] = max(0, (now - _ts(p["resolved_on"])).days) if p.get("resolved_on") else None
            except Exception:
                p["age_days"] = None
        n = len(precedents)
        status = "none" if n == 0 else ("single" if n == 1 else "multiple")
        direct = [p for p in precedents if p["relation"] == "same_vendor_same_issue"]
        decisions = {("approve" if (p.get("decision") or "").startswith("approve") else p.get("decision")) for p in direct}
        if not direct:
            strength = {"level": "none" if not precedents else "related",
                        "label": "No direct precedent" if not precedents else "Related cases only, from other vendors"}
        elif len(decisions) > 1:
            strength = {"level": "conflicting", "label": f"Conflicting decisions across {len(direct)} cases"}
        elif len(direct) >= 3:
            strength = {"level": "established", "label": f"Established pattern, {len(direct)} consistent cases"}
        else:
            strength = {"level": "emerging", "label": f"Emerging pattern, {len(direct)} case" + ("s" if len(direct) > 1 else "")}
        by_kind = lambda k: [x for x in notes.values() if x["kind"] == k]
        return {
            "enabled": True,
            "bank_id": self.bank_id,
            "status": status,
            "precedent_count": n,
            "precedents": precedents,
            "strength": strength,
            "vendor_notes": by_kind("vendor_note"),
            "reviewer_preferences": by_kind("reviewer_preference"),
            "policies": by_kind("policy")[:3],
            "reviewer": reviewer,
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

    async def ledger(self) -> list[dict]:
        """Everything the bank holds, one row per retained document (case or note)."""
        await self.ensure_bank()
        resp = await self.client.documents.list_documents(self.bank_id, limit=200)
        rows = []
        for d in resp.items or []:
            tags = d.tags or []

            def tag(prefix, tags=tags):
                return [t.split(":", 1)[1] for t in tags if t.startswith(prefix)]

            kind = (tag("kind:") or ["case"])[0]
            rows.append({"id": d.id, "kind": kind, "kind_label": NOTE_KINDS.get(kind, "Resolved case"),
                         "created_at": d.created_at, "updated_at": d.updated_at, "memory_units": d.memory_unit_count,
                         "vendor_id": (tag("vendor:") or [None])[0], "decision": (tag("decision:") or [None])[0],
                         "reviewer": (tag("reviewer:") or [None])[0], "exception_codes": tag("exc:"), "tags": tags})
        rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)
        return rows

    async def forget(self, document_id: str) -> dict:
        await self.ensure_bank()
        await self.client.documents.delete_document(self.bank_id, document_id)
        log.info("[hindsight] forgot document %s", document_id)
        return {"forgotten": document_id}

    async def playbook(self) -> list[dict]:
        await self.ensure_bank()
        resp = await self.client.alist_mental_models(bank_id=self.bank_id, detail="content")
        wanted = {m["id"] for m in MENTAL_MODELS}
        return [{"id": m.id, "name": m.name, "content": m.content, "last_refreshed_at": m.last_refreshed_at,
                 "is_stale": m.is_stale, "source_query": m.source_query}
                for m in resp.items or [] if m.id in wanted]

    async def refresh_playbook(self) -> dict:
        await self.ensure_bank()
        ops = []
        for mm in MENTAL_MODELS:
            try:
                r = await self.client.arefresh_mental_model(self.bank_id, mm["id"])
                ops.append({"id": mm["id"], "operation_id": getattr(r, "operation_id", None)})
            except Exception as e:
                ops.append({"id": mm["id"], "error": str(e)})
        return {"refreshing": ops}

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
