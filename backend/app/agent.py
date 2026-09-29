"""The AP exception agent.

Pipeline: deterministic checks and Hindsight recall always run first, so the
evidence never depends on the model remembering to call a tool. The LLM then
gets that evidence plus tools to dig further, and writes the explanation and
recommendation as JSON. Its output is validated against what Hindsight actually
returned, so it cannot cite a precedent that was never retrieved.
"""

from __future__ import annotations

import json
import logging
import re
import time

from groq import AsyncGroq, BadRequestError

from .config import Settings
from .data_store import DataStore
from .memory import MemoryService, exc_tag, vendor_tag
from .rules import approval_requirement, run_checks, vendor_baseline

log = logging.getLogger("precedent.agent")

ACTIONS = {"approve", "approve_with_conditions", "hold", "reject", "escalate"}
PRECEDENT_STATUSES = {"none", "applies", "partially_applies", "does_not_apply", "mixed"}
CASE_ID_RE = re.compile(r"CASE-[A-Z0-9\-]+")

SYSTEM_PROMPT = """You are Precedent, an accounts payable exception analyst working for Nirmaan Foods Pvt Ltd in India.
A human AP reviewer makes every final decision. You never approve or release payment yourself; you recommend.

Ground rules:
1. RULE_CHECKS are computed by deterministic code and are ground truth. Never recompute, round differently or invent amounts, quantities, dates or PO numbers. Quote them as given.
2. HINDSIGHT_MEMORY contains past cases that the memory system actually retrieved. You may only cite case_ids that appear there or that a search_hindsight_memory tool call returned. If memory status is "none" or memory is disabled, say plainly that there is no relevant precedent in memory and do not imply one exists.
3. For every precedent, decide whether it really applies. Compare the specific facts that made the past case acceptable or unacceptable (for example an amended PO, a matching goods receipt, a contract clause, a call-back) with the current evidence. Set applies=true only when every fact that justified the past decision is also present in the current invoice. If any of those facts is missing, or the current invoice has an exception the past case did not have, set applies=false and say which fact is missing.
4. A past approval never removes the need to verify the current invoice. A past fraud or rejection should make you more cautious.
5. Use tools only if you need information that is not already in the evidence.
6. Write for a busy reviewer: specific, short, no filler. Use Indian rupee amounts as given (Rs).
7. Plain punctuation only: no em dashes, no en dashes, and no slash shorthand. Write "PO and GRN", not "PO/GRN".

When you are done, reply with ONLY a JSON object with exactly these keys:
{
  "headline": "one sentence stating the main issue and what to do",
  "explanation": "2 to 5 sentences explaining the discrepancies using the evidence",
  "issues": [{"code": "RULE_CODE", "explanation": "one or two sentences"}],
  "precedent": {
    "status": "none | applies | partially_applies | does_not_apply | mixed",
    "summary": "how past cases bear on this invoice, or that memory had nothing relevant",
    "cases": [{"case_id": "CASE-...", "applies": false, "why": "one sentence"}]
  },
  "recommendation": {
    "action": "approve | approve_with_conditions | hold | reject | escalate",
    "rationale": "2 to 3 sentences",
    "conditions": ["specific condition or verification step"]
  },
  "checklist": ["concrete verification step for the reviewer"],
  "memory_influence": "one sentence on how memory changed your recommendation, or 'No memory was used.'"
}"""

TOOLS = [
    {"type": "function", "function": {
        "name": "get_vendor", "description": "Vendor master record: GSTIN, state, MSME status, payment terms, onboarding date, bank on file.",
        "parameters": {"type": "object", "properties": {"vendor_id": {"type": "string"}}, "required": ["vendor_id"]}}},
    {"type": "function", "function": {
        "name": "get_invoice", "description": "Full invoice record with line items and tax split.",
        "parameters": {"type": "object", "properties": {"invoice_id": {"type": "string"}}, "required": ["invoice_id"]}}},
    {"type": "function", "function": {
        "name": "get_purchase_order", "description": "Purchase order with lines, rates and amendment history.",
        "parameters": {"type": "object", "properties": {"po_id": {"type": "string"}}, "required": ["po_id"]}}},
    {"type": "function", "function": {
        "name": "check_invoice", "description": "Run the deterministic AP rule checks on an invoice.",
        "parameters": {"type": "object", "properties": {"invoice_id": {"type": "string"}}, "required": ["invoice_id"]}}},
    {"type": "function", "function": {
        "name": "check_vendor_history", "description": "Paid invoice history and 6-month amount baseline for the vendor of an invoice.",
        "parameters": {"type": "object", "properties": {"invoice_id": {"type": "string"}}, "required": ["invoice_id"]}}},
    {"type": "function", "function": {
        "name": "get_approval_rule", "description": "Approval tier and approver role for an amount in INR.",
        "parameters": {"type": "object", "properties": {"amount": {"type": "number"}}, "required": ["amount"]}}},
    {"type": "function", "function": {
        "name": "search_hindsight_memory",
        "description": "Search the team's Hindsight memory of resolved AP exceptions. Filter by vendor_id or exception_code (for example BANK_DETAILS_CHANGED, AMOUNT_SPIKE, GST_MISMATCH).",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "vendor_id": {"type": "string"}, "exception_code": {"type": "string"}},
            "required": ["query"]}}},
]


def _trim_analysis(a: dict) -> dict:
    """Evidence pack sent to the LLM. Bank account is reduced to last 4 digits already."""
    inv, v, po, grn = a["invoice"], a["vendor"], a["purchase_order"], a["goods_receipt"]
    return {
        "invoice": {k: inv.get(k) for k in ("id", "invoice_no", "invoice_date", "po_id", "grn_id", "subtotal", "tax",
                                             "tax_total", "total", "payment_terms", "due_date", "bank_account_last4", "notes")}
        | {"lines": [{k: ln[k] for k in ("item_code", "description", "qty", "unit", "unit_price", "gst_rate", "amount")} for ln in inv["lines"]]},
        "vendor": {k: v.get(k) for k in ("id", "name", "gstin", "state", "category", "supply_type", "msme", "payment_terms", "onboarded_on")}
        | {"bank_on_file_last4": v["bank"]["account_last4"]},
        "purchase_order": None if not po else {"id": po["id"], "po_date": po["po_date"], "lines": po["lines"], "amendments": po["amendments"]},
        "goods_receipt": grn,
        "po_comparison": a["po_comparison"],
        "findings": a["findings"],
        "vendor_baseline": {k: a["baseline"][k] for k in ("invoice_count", "median", "min", "max", "ratio")},
        "payment": a["payment"],
        "approval": a["approval"],
    }


def _memory_block(mem: dict | None) -> dict:
    if not mem or not mem.get("enabled"):
        return {"enabled": False, "note": "Memory is disabled for this run. Do not reference past cases."}
    return {
        "enabled": True,
        "status": mem["status"],
        "note": {"none": "Hindsight returned no qualifying precedent for this vendor or these exception types.",
                 "single": "Hindsight returned one qualifying precedent.",
                 "multiple": "Hindsight returned several qualifying precedents; weigh each one."}[mem["status"]],
        "precedents": [{k: p[k] for k in ("case_id", "relation_label", "invoice_no", "vendor_name", "decision", "reviewer",
                                           "resolved_on", "exception_codes", "facts")} for p in mem["precedents"]],
        "same_vendor_other_exceptions": [{k: p[k] for k in ("case_id", "invoice_no", "decision", "exception_codes", "facts")}
                                         for p in mem["vendor_context"]],
        "consolidated_patterns": [p["text"] for p in mem["patterns"]],
    }


PUNCT = {"—": ", ", "–": "-", "‑": "-", "‐": "-", "’": "'", "‘": "'",
         "“": '"', "”": '"', " ": " ", " ": " "}


def _clean(obj):
    """Normalise model punctuation so the UI copy stays plain."""
    if isinstance(obj, str):
        for k, v in PUNCT.items():
            obj = obj.replace(k, v)
        return re.sub(r"(PO|GRN|invoice|vendor)/(PO|GRN|invoice|vendor)", r" and ", obj)
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    return obj


def _parse_json(text: str | None) -> dict | None:
    if not text:
        return None
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class Agent:
    def __init__(self, settings: Settings, store: DataStore, memory: MemoryService):
        self.settings = settings
        self.store = store
        self.memory = memory
        self.llm = AsyncGroq(api_key=settings.groq_api_key) if settings.groq_api_key else None

    # ------------------------------------------------------------------ tools

    async def _run_tool(self, name: str, args: dict, ctx: dict) -> dict:
        s = self.store
        if name == "get_vendor":
            v = s.get_vendor(args.get("vendor_id", ""))
            return v and {**v, "bank": {"bank_name": v["bank"]["bank_name"], "account_last4": v["bank"]["account_last4"]}} or {"error": "vendor not found"}
        if name == "get_invoice":
            return s.get_invoice(args.get("invoice_id", "")) or {"error": "invoice not found"}
        if name == "get_purchase_order":
            return s.get_purchase_order(args.get("po_id")) or {"error": "purchase order not found"}
        if name == "check_invoice":
            try:
                a = run_checks(s, args.get("invoice_id", ""))
            except KeyError:
                return {"error": "invoice not found"}
            return {"findings": a["findings"], "approval": a["approval"], "status": a["status"]}
        if name == "check_vendor_history":
            inv = s.get_invoice(args.get("invoice_id", ""))
            return vendor_baseline(inv, s, s.approval_rules) if inv else {"error": "invoice not found"}
        if name == "get_approval_rule":
            amt = float(args.get("amount", 0))
            return approval_requirement({"total": amt}, [], s.approval_rules)
        if name == "search_hindsight_memory":
            if not ctx["use_memory"]:
                return {"error": "Memory is disabled for this run."}
            tags = [vendor_tag(args["vendor_id"])] if args.get("vendor_id") else (
                [exc_tag(args["exception_code"])] if args.get("exception_code") else None)
            results = await self.memory.client.arecall(bank_id=self.memory.bank_id, query=args.get("query", "")[:1000],
                                                       tags=tags, tags_match="any_strict" if tags else "any", budget="mid")
            cases: dict[str, dict] = {}
            for r in results.results or []:
                md = r.metadata or {}
                cid = md.get("case_id") or r.document_id
                if not cid:
                    continue
                c = cases.setdefault(cid, {"case_id": cid, "vendor_name": md.get("vendor_name"), "decision": md.get("decision"),
                                           "exception_codes": md.get("exception_codes"), "facts": []})
                if len(c["facts"]) < 4:
                    c["facts"].append(r.text)
            ctx["retrieved_ids"].update(cases)
            return {"cases": list(cases.values()) or [], "note": None if cases else "No matching memories."}
        return {"error": f"unknown tool {name}"}

    # ------------------------------------------------------------------ main entry

    async def analyze(self, invoice_id: str, use_memory: bool = True) -> dict:
        t0 = time.perf_counter()
        trace: list[dict] = []
        analysis = run_checks(self.store, invoice_id)
        inv = analysis["invoice"]
        trace += [
            {"tool": "get_invoice", "by": "pipeline", "summary": f"{inv['invoice_no']}, {len(inv['lines'])} line(s), total {inv['total']}"},
            {"tool": "get_vendor", "by": "pipeline", "summary": analysis["vendor"]["name"]},
            {"tool": "get_purchase_order", "by": "pipeline", "summary": inv.get("po_id") or "no PO on invoice"},
            {"tool": "check_vendor_history", "by": "pipeline",
             "summary": f"{analysis['baseline']['invoice_count']} paid invoices, median {analysis['baseline']['median']}"},
            {"tool": "check_invoice", "by": "pipeline",
             "summary": f"{len(analysis['findings'])} finding(s): {', '.join(analysis['exception_codes']) or 'none'}"},
            {"tool": "get_approval_rule", "by": "pipeline", "summary": analysis["approval"]["approver_role"]},
        ]

        memory = {"enabled": False, "status": "disabled", "precedents": [], "vendor_context": [], "patterns": [],
                  "gated_out": [], "precedent_count": 0}
        if use_memory:
            try:
                memory = await self.memory.recall_precedents(analysis)
                trace.append({"tool": "search_hindsight_memory", "by": "pipeline",
                              "summary": f"{memory['raw_result_count']} memories retrieved, {memory['precedent_count']} qualified as precedent "
                                         f"({memory['status']}), {len(memory['gated_out'])} gated out"})
            except Exception as e:  # memory outage should not block analysis, but it must be visible
                log.exception("recall failed")
                memory = {**memory, "enabled": True, "status": "error", "error": str(e)}
                trace.append({"tool": "search_hindsight_memory", "by": "pipeline", "summary": f"FAILED: {e}"})

        ctx = {"use_memory": use_memory,
               "retrieved_ids": {p["case_id"] for p in memory.get("precedents", []) + memory.get("vendor_context", [])}}
        agent_out, llm_meta = await self._reason(analysis, memory, ctx, trace)
        warnings = self._validate(agent_out, memory, ctx)

        return {
            "invoice_id": invoice_id,
            "use_memory": use_memory,
            "checks": analysis,
            "memory": memory,
            "agent": agent_out,
            "guardrail_warnings": warnings,
            "trace": trace,
            "llm": llm_meta,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }

    async def _reason(self, analysis: dict, memory: dict, ctx: dict, trace: list) -> tuple[dict, dict]:
        meta = {"model": self.settings.groq_model, "tool_rounds": 0, "fallback": None}
        if not self.llm:
            meta["fallback"] = "GROQ_API_KEY not configured"
            return self._deterministic_summary(analysis, memory), meta

        mem_block = memory if memory.get("status") not in ("error",) else {"enabled": False}
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Analyse this invoice exception.\n\nRULE_CHECKS:\n"
             + json.dumps(_trim_analysis(analysis), default=str)
             + "\n\nHINDSIGHT_MEMORY:\n" + json.dumps(_memory_block(mem_block), default=str)},
        ]
        tools = TOOLS if ctx["use_memory"] else [t for t in TOOLS if t["function"]["name"] != "search_hindsight_memory"]
        content = None
        try:
            for _ in range(4):
                resp = await self._chat(messages, tools=tools)
                msg = resp.choices[0].message
                if msg.tool_calls:
                    meta["tool_rounds"] += 1
                    messages.append({"role": "assistant", "content": msg.content or "",
                                     "tool_calls": [{"id": tc.id, "type": "function",
                                                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                                    for tc in msg.tool_calls]})
                    for tc in msg.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        result = await self._run_tool(tc.function.name, args, ctx)
                        trace.append({"tool": tc.function.name, "by": "llm", "args": args,
                                      "summary": json.dumps(result, default=str)[:240]})
                        messages.append({"role": "tool", "tool_call_id": tc.id,
                                         "content": json.dumps(result, default=str)[:6000]})
                    continue
                content = msg.content
                break
        except BadRequestError as e:
            # Groq returns tool_use_failed when the model emits a malformed tool call.
            log.warning("tool loop failed, retrying without tools: %s", e)
            meta["fallback"] = "tool call failed, answered without tools"
            trace.append({"tool": "llm", "by": "pipeline", "summary": "Tool call rejected by provider, continuing without tools"})
        except Exception as e:
            log.exception("LLM call failed")
            meta["fallback"] = f"LLM error: {e}"
            return self._deterministic_summary(analysis, memory), meta

        parsed = _parse_json(content)
        if parsed is None:
            try:
                messages.append({"role": "user", "content": "Reply now with only the JSON object described in the instructions."})
                resp = await self._chat(messages, json_mode=True)
                parsed = _parse_json(resp.choices[0].message.content)
            except Exception as e:
                log.exception("JSON retry failed")
                meta["fallback"] = f"LLM error: {e}"
        if parsed is None:
            meta["fallback"] = meta["fallback"] or "LLM returned unparseable output"
            return self._deterministic_summary(analysis, memory), meta
        return _clean(parsed), meta

    async def _chat(self, messages: list, tools: list | None = None, json_mode: bool = False):
        kwargs = {"model": self.settings.groq_model, "messages": messages, "temperature": 0, "max_completion_tokens": 3000}
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if "gpt-oss" in self.settings.groq_model:
            kwargs["reasoning_effort"] = "medium"
        return await self.llm.chat.completions.create(**kwargs)

    # ------------------------------------------------------------------ guardrails

    @staticmethod
    def _validate(out: dict, memory: dict, ctx: dict) -> list[str]:
        """Strip any precedent the memory system did not actually return."""
        warnings = []
        allowed = ctx["retrieved_ids"] if memory.get("enabled") else set()
        prec = out.setdefault("precedent", {})
        cases = prec.get("cases") or []
        kept = []
        for c in cases:
            if c.get("case_id") in allowed:
                kept.append(c)
            else:
                warnings.append(f"Removed citation of {c.get('case_id')}: not returned by Hindsight in this run.")
        prec["cases"] = kept
        if prec.get("status") not in PRECEDENT_STATUSES:
            prec["status"] = "none"
        if kept:  # the overall label must agree with the per-case verdicts
            verdicts = {bool(c.get("applies")) for c in kept}
            if verdicts == {False}:
                prec["status"] = "does_not_apply"
            elif verdicts == {True} and prec["status"] not in ("applies", "partially_applies"):
                prec["status"] = "applies"
            elif len(verdicts) == 2:
                prec["status"] = "mixed"
        if not kept and prec.get("status") != "none":
            warnings.append(f"Precedent status '{prec.get('status')}' reset to 'none': no retrieved case supports it.")
            prec["status"] = "none"
            if not memory.get("enabled"):
                prec["summary"] = "Memory was disabled for this run."
        text = json.dumps(out)
        for cid in set(CASE_ID_RE.findall(text)) - allowed:
            warnings.append(f"Text mentions {cid}, which Hindsight did not return in this run.")
        rec = out.setdefault("recommendation", {})
        if rec.get("action") not in ACTIONS:
            warnings.append(f"Unknown action '{rec.get('action')}' replaced with 'hold'.")
            rec["action"] = "hold"
        out.setdefault("checklist", [])
        out.setdefault("issues", [])
        return warnings

    @staticmethod
    def _deterministic_summary(a: dict, memory: dict) -> dict:
        """Used only when the LLM is unavailable. Clearly marked as such."""
        issues = [f for f in a["findings"] if f["severity"] != "info"]
        high = any(f["severity"] == "high" for f in issues)
        action = "approve" if not issues else ("hold" if high else "approve_with_conditions")
        return {
            "headline": "LLM unavailable. Summary generated from rule checks only.",
            "explanation": " ".join(f["detail"] for f in issues) or "All rule checks passed.",
            "issues": [{"code": f["code"], "explanation": f["detail"]} for f in issues],
            "precedent": {"status": "none", "summary": "Not assessed without the LLM.", "cases": []},
            "recommendation": {"action": action, "rationale": "Derived from rule severity only.", "conditions": []},
            "checklist": [f["title"] for f in issues],
            "memory_influence": "No memory was used.",
        }
