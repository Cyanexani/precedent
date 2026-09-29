"""HTTP API for Precedent."""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .agent import Agent
from .config import get_settings
from .data_store import get_store
from .memory import NOTE_KINDS, MemoryService
from .rules import run_checks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("precedent.api")

state: dict = {"resolutions": {}, "analyses": [], "resolved_events": []}

ACTION_CLASS = {"approve": "approve", "approve_with_conditions": "approve", "hold": "hold", "escalate": "hold", "reject": "reject"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = get_store()
    memory = MemoryService(settings)
    state.update(settings=settings, store=store, memory=memory, agent=Agent(settings, store, memory))
    if settings.missing:
        log.warning("Missing configuration: %s. Copy .env.example to .env and fill it in.", ", ".join(settings.missing))
    yield
    try:
        await memory.client.aclose()
    except Exception:
        pass


app = FastAPI(title="Precedent AP exception agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- helpers


def require_config() -> None:
    missing = state["settings"].missing
    if missing:
        raise HTTPException(503, f"Server is not configured. Missing: {', '.join(missing)}. See README setup.")


def get_invoice_or_404(invoice_id: str) -> dict:
    inv = state["store"].get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, f"Invoice {invoice_id} not found")
    return inv


def case_id_for(invoice_no: str) -> str:
    return "CASE-" + re.sub(r"[^A-Z0-9]+", "-", invoice_no.upper()).strip("-")


def review_facts(a: dict) -> list[str]:
    """The distinguishing facts a future reviewer needs to judge whether this case is comparable."""
    inv, po, grn = a["invoice"], a["purchase_order"], a["goods_receipt"]
    facts = []
    if not po:
        facts.append("No purchase order was referenced on the invoice.")
    else:
        po_qty = ", ".join(f"{ln['qty']} {ln['unit']} {ln['item_code']} at Rs {ln['unit_price']}" for ln in po["lines"])
        facts.append(f"PO {po['id']} dated {po['po_date']} covered {po_qty}.")
        if po["amendments"]:
            for am in po["amendments"]:
                facts.append(f"PO amendment on record dated {am['date']} by {am['by']}: {am['change']} ({am['reason']}).")
        else:
            facts.append("The PO had no amendments.")
    if grn:
        rec = {ln["item_code"]: ln["qty_received"] for ln in grn["lines"]}
        match = all(rec.get(ln["item_code"], 0) >= ln["qty"] for ln in inv["lines"])
        facts.append(f"Goods receipt {grn['id']} " + ("matched the invoiced quantity." if match else
                     "recorded less than the invoiced quantity: " + ", ".join(f"{rec.get(ln['item_code'], 0)} received vs {ln['qty']} invoiced" for ln in inv["lines"]) + "."))
    b = a["baseline"]
    if b["ratio"] is not None:
        facts.append(f"Invoice total was {b['ratio']}x the vendor's 6-month median of Rs {b['median']:,.2f}.")
    if inv.get("bank_account_last4") != a["vendor"]["bank"]["account_last4"]:
        facts.append(f"Invoice bank account ending {inv['bank_account_last4']} differed from vendor master ending {a['vendor']['bank']['account_last4']}.")
    return facts


# ---------------------------------------------------------------- models


class AnalyzeRequest(BaseModel):
    use_memory: bool = True
    reviewer: str | None = Field(default=None, max_length=60)


class CompareRequest(BaseModel):
    reviewer: str | None = Field(default=None, max_length=60)


class NoteRequest(BaseModel):
    kind: Literal["vendor_note", "reviewer_preference", "policy"]
    text: str = Field(min_length=15, max_length=2000)
    author: str = Field(min_length=2, max_length=60)
    vendor_id: str | None = None
    reviewer: str | None = Field(default=None, max_length=60)


class ResolveRequest(BaseModel):
    decision: Literal["approve", "approve_with_conditions", "hold", "reject"]
    reviewer: str = Field(min_length=2, max_length=60)
    reason: str = Field(min_length=15, max_length=2000)
    evidence: list[str] = Field(default_factory=list, max_length=12)
    conditions: list[str] = Field(default_factory=list, max_length=8)
    agent_action: str | None = None
    agent_used_memory: bool | None = None

    @field_validator("reviewer", "reason")
    @classmethod
    def strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("evidence", "conditions")
    @classmethod
    def clean_list(cls, v: list[str]) -> list[str]:
        return [s.strip()[:240] for s in v if s and s.strip()]


class AskRequest(BaseModel):
    question: str = Field(min_length=5, max_length=500)
    vendor_id: str | None = None


# ---------------------------------------------------------------- routes


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/config")
async def config():
    s = state["settings"]
    return {"configured": not s.missing, "missing": s.missing, "model": s.groq_model, "bank_id": s.hindsight_bank_id,
            "hindsight_base_url": s.hindsight_base_url, "company": state["store"].company}


@app.get("/api/invoices")
async def list_invoices():
    store = state["store"]
    out = []
    for inv in sorted(store.pending_invoices(), key=lambda i: i["id"]):
        a = run_checks(store, inv["id"])
        out.append({
            "id": inv["id"], "invoice_no": inv["invoice_no"], "vendor_id": inv["vendor_id"],
            "vendor_name": a["vendor"]["name"], "invoice_date": inv["invoice_date"], "total": inv["total"],
            "scenario": inv.get("scenario"), "status": a["status"], "max_severity": a["max_severity"],
            "exception_codes": a["exception_codes"], "approver_role": a["approval"]["approver_role"],
            "resolution": state["resolutions"].get(inv["id"]),
            "case_id": case_id_for(inv["invoice_no"]),
        })
    return out


def record_analysis(r: dict) -> None:
    state["analyses"].append({
        "n": len(state["analyses"]) + 1, "invoice_id": r["invoice_id"], "use_memory": r["use_memory"],
        "precedent_count": r["memory"].get("precedent_count", 0),
        "notes_count": len(r["memory"].get("vendor_notes", [])) + len(r["memory"].get("reviewer_preferences", [])),
        "precedent_status": r["agent"].get("precedent", {}).get("status"),
        "action": r["agent"].get("recommendation", {}).get("action"),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


@app.get("/api/invoices/{invoice_id}")
async def invoice_detail(invoice_id: str):
    get_invoice_or_404(invoice_id)
    return {**run_checks(state["store"], invoice_id), "resolution": state["resolutions"].get(invoice_id)}


@app.post("/api/invoices/{invoice_id}/analyze")
async def analyze(invoice_id: str, body: AnalyzeRequest):
    get_invoice_or_404(invoice_id)
    require_config()
    r = await state["agent"].analyze(invoice_id, use_memory=body.use_memory, reviewer=body.reviewer)
    record_analysis(r)
    return r


@app.post("/api/invoices/{invoice_id}/compare")
async def compare(invoice_id: str, body: CompareRequest | None = None):
    """Same invoice, same checks, same model: once without memory, once with it."""
    get_invoice_or_404(invoice_id)
    require_config()
    reviewer = body.reviewer if body else None
    without, with_ = await asyncio.gather(state["agent"].analyze(invoice_id, use_memory=False, reviewer=reviewer),
                                          state["agent"].analyze(invoice_id, use_memory=True, reviewer=reviewer))
    record_analysis(without)
    record_analysis(with_)
    return {"without_memory": without, "with_memory": with_}


@app.post("/api/invoices/{invoice_id}/resolve")
async def resolve(invoice_id: str, body: ResolveRequest):
    inv = get_invoice_or_404(invoice_id)
    require_config()
    a = run_checks(state["store"], invoice_id)  # recomputed server side, never trusted from the client
    exc = [f for f in a["findings"] if f["severity"] != "info"]
    now = datetime.now(timezone.utc)
    case = {
        "case_id": case_id_for(inv["invoice_no"]),
        "invoice_id": inv["id"],
        "invoice_no": inv["invoice_no"],
        "invoice_date": inv["invoice_date"],
        "vendor_id": inv["vendor_id"],
        "vendor_name": a["vendor"]["name"],
        "total": inv["total"],
        "exception_codes": a["exception_codes"] or ["NONE"],
        "findings_text": " ".join(f"{f['code']}: {f['detail']}" for f in exc) or "No exceptions.",
        "facts": review_facts(a),
        "decision": body.decision,
        "reviewer": body.reviewer,
        "resolved_on": now.isoformat(timespec="seconds"),
        "reason": body.reason,
        "evidence": body.evidence,
        "conditions": body.conditions,
        "source": "reviewer",
        "agent_action": body.agent_action,
    }
    try:
        result = await state["memory"].retain_case(case)
    except Exception as e:
        log.exception("retain failed")
        raise HTTPException(502, f"Hindsight retain failed: {e}") from e
    record = {"case_id": case["case_id"], "decision": body.decision, "reviewer": body.reviewer,
              "resolved_on": case["resolved_on"], "retained": result["success"]}
    state["resolutions"][invoice_id] = record
    if body.agent_action:
        state["resolved_events"].append({
            "invoice_id": invoice_id, "decision": body.decision, "agent_action": body.agent_action,
            "agent_used_memory": bool(body.agent_used_memory),
            "agreed": ACTION_CLASS.get(body.agent_action) == ACTION_CLASS.get(body.decision),
        })
    return {**record, "memory": result}


@app.get("/api/memory/stats")
async def memory_stats():
    require_config()
    try:
        return await state["memory"].stats()
    except Exception as e:
        raise HTTPException(502, f"Hindsight unavailable: {e}") from e


@app.post("/api/memory/seed-history")
async def seed_history():
    """Retain the team's past resolved exceptions (the story's vendor is deliberately not among them)."""
    require_config()
    store = state["store"]
    cases = [{**c, "vendor_name": store.vendors[c["vendor_id"]]["name"], "source": "team_history"}
             for c in store.historical_cases]
    notes = [{**n, "vendor_name": store.vendors[n["vendor_id"]]["name"] if n.get("vendor_id") else None}
             for n in store.team_notes]
    try:
        return await state["memory"].retain_cases(cases, notes)
    except Exception as e:
        log.exception("seed failed")
        raise HTTPException(502, f"Hindsight retain failed: {e}") from e


@app.post("/api/memory/reset")
async def memory_reset():
    require_config()
    try:
        out = await state["memory"].reset()
    except Exception as e:
        raise HTTPException(502, f"Hindsight reset failed: {e}") from e
    state["resolutions"].clear()
    state["analyses"].clear()
    state["resolved_events"].clear()
    return out


@app.post("/api/memory/ask")
async def memory_ask(body: AskRequest):
    require_config()
    tags = [f"vendor:{body.vendor_id}"] if body.vendor_id else None
    try:
        return await state["memory"].reflect(body.question, tags=tags)
    except Exception as e:
        raise HTTPException(502, f"Hindsight reflect failed: {e}") from e


@app.get("/api/vendors")
async def vendors():
    return [{"id": v["id"], "name": v["name"]} for v in state["store"].vendors.values()]


@app.post("/api/memory/notes")
async def add_note(body: NoteRequest):
    """Teach the memory something that is not an invoice resolution."""
    require_config()
    store = state["store"]
    if body.kind == "vendor_note" and (not body.vendor_id or body.vendor_id not in store.vendors):
        raise HTTPException(422, "A vendor communication needs a valid vendor_id")
    if body.kind == "reviewer_preference" and not (body.reviewer or "").strip():
        raise HTTPException(422, "A reviewer preference needs the reviewer's name")
    now = datetime.now(timezone.utc)
    note = {
        "note_id": f"NOTE-{body.kind.upper().replace('_', '-')}-{now.strftime('%Y%m%d%H%M%S')}",
        "kind": body.kind, "text": body.text.strip(), "author": body.author.strip(),
        "vendor_id": body.vendor_id if body.kind == "vendor_note" else None,
        "vendor_name": store.vendors[body.vendor_id]["name"] if body.kind == "vendor_note" else None,
        "reviewer": body.reviewer.strip() if body.kind == "reviewer_preference" and body.reviewer else None,
        "created_on": now.isoformat(timespec="seconds"),
    }
    try:
        return await state["memory"].retain_note(note)
    except Exception as e:
        raise HTTPException(502, f"Hindsight retain failed: {e}") from e


@app.get("/api/memory/ledger")
async def memory_ledger():
    require_config()
    try:
        return await state["memory"].ledger()
    except Exception as e:
        raise HTTPException(502, f"Hindsight unavailable: {e}") from e


@app.delete("/api/memory/documents/{document_id}")
async def memory_forget(document_id: str):
    require_config()
    try:
        out = await state["memory"].forget(document_id)
    except Exception as e:
        raise HTTPException(502, f"Hindsight delete failed: {e}") from e
    for inv_id, res in list(state["resolutions"].items()):
        if res.get("case_id") == document_id:
            del state["resolutions"][inv_id]
    return out


@app.get("/api/memory/playbook")
async def memory_playbook():
    require_config()
    try:
        return await state["memory"].playbook()
    except Exception as e:
        raise HTTPException(502, f"Hindsight unavailable: {e}") from e


@app.post("/api/memory/playbook/refresh")
async def memory_playbook_refresh():
    require_config()
    try:
        return await state["memory"].refresh_playbook()
    except Exception as e:
        raise HTTPException(502, f"Hindsight refresh failed: {e}") from e


@app.post("/api/triage")
async def triage():
    """Check the whole queue against memory (recall only, no LLM) so reviewers know where precedents exist."""
    require_config()
    store, memory = state["store"], state["memory"]
    sem = asyncio.Semaphore(4)

    async def one(inv):
        async with sem:
            a = run_checks(store, inv["id"])
            try:
                m = await memory.recall_precedents(a, lite=True)
            except Exception as e:
                return inv["id"], {"error": str(e)}
            return inv["id"], {
                "precedent_count": m["precedent_count"], "status": m["status"],
                "strength": m["strength"]["label"], "vendor_notes": len(m["vendor_notes"]),
                "top": [{"case_id": p["case_id"], "relation": p["relation_label"], "decision": p["decision"]}
                        for p in m["precedents"][:3]],
            }

    results = await asyncio.gather(*(one(i) for i in store.pending_invoices()))
    return dict(results)


@app.get("/api/metrics")
async def metrics():
    """Honest counters from this server session: nothing here is estimated."""
    an = state["analyses"]
    mem_runs = [a for a in an if a["use_memory"]]
    res = state["resolved_events"]

    def rate(rows):
        return None if not rows else round(100 * sum(r["agreed"] for r in rows) / len(rows))

    return {
        "analyses": len(an),
        "memory_runs": len(mem_runs),
        "runs_with_precedent": sum(1 for a in mem_runs if a["precedent_count"] > 0),
        "precedents_ruled_out": sum(1 for a in mem_runs if a["precedent_status"] == "does_not_apply"),
        "resolutions_retained": len(state["resolutions"]),
        "agreement_with_memory": rate([r for r in res if r["agent_used_memory"]]),
        "agreement_without_memory": rate([r for r in res if not r["agent_used_memory"]]),
        "agreement_samples": {"with_memory": sum(1 for r in res if r["agent_used_memory"]),
                              "without_memory": sum(1 for r in res if not r["agent_used_memory"])},
        "timeline": [{"n": a["n"], "invoice_id": a["invoice_id"], "use_memory": a["use_memory"],
                      "precedent_count": a["precedent_count"], "notes_count": a["notes_count"]} for a in an[-40:]],
        "note_kinds": NOTE_KINDS,
    }


# Serve the built frontend when it exists (single process deploys).
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
