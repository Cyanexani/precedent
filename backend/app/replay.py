"""Replay a simulated quarter to measure whether memory makes the agent better.

For each of the 14 replay invoices, in arrival order:
  1. run the rule checks,
  2. recall from a dedicated replay bank that starts empty,
  3. ask the agent to predict the reviewer's decision twice: with that recall, and with no memory,
  4. compare both predictions with the decision the reviewer actually recorded,
  5. retain the recorded decision so later invoices can recall it.

The predictions are live model calls and the recall is live Hindsight. The recorded
decisions come from the dataset. Nothing in the result is estimated.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .agent import Agent
from .cases import build_case
from .config import Settings
from .data_store import DataStore
from .memory import MemoryService
from .rules import run_checks

log = logging.getLogger("precedent.replay")

RESULT_FILE = Path(__file__).resolve().parent.parent / "data" / "runtime" / "replay_latest.json"
# A real run, committed so a fresh deployment has something to show before its first run.
SAMPLE_FILE = Path(__file__).resolve().parent.parent / "data" / "replay_sample.json"
ACTION_CLASS = {"approve": "approve", "approve_with_conditions": "approve", "hold": "hold", "escalate": "hold", "reject": "reject"}


def _pct(hits: int, n: int) -> float | None:
    return None if n == 0 else round(100 * hits / n, 1)


def summarise(steps: list[dict]) -> dict:
    cum, on_hits, off_hits = [], 0, 0
    for i, s in enumerate(steps, 1):
        on_hits += s["with_memory"]["agreed"]
        off_hits += s["without_memory"]["agreed"]
        cum.append({"step": i, "with_memory": _pct(on_hits, i), "without_memory": _pct(off_hits, i)})
    half = len(steps) // 2
    first, second = steps[:half], steps[half:]
    rate = lambda rows, arm: _pct(sum(r[arm]["agreed"] for r in rows), len(rows))
    return {
        "steps_done": len(steps),
        "agreement_with_memory": _pct(on_hits, len(steps)),
        "agreement_without_memory": _pct(off_hits, len(steps)),
        "first_half": {"with_memory": rate(first, "with_memory"), "without_memory": rate(first, "without_memory"), "n": len(first)},
        "second_half": {"with_memory": rate(second, "with_memory"), "without_memory": rate(second, "without_memory"), "n": len(second)},
        "steps_with_precedent": sum(1 for s in steps if s["memory"]["precedent_count"] > 0),
        "memory_changed_decision": sum(1 for s in steps
                                       if ACTION_CLASS.get(s["with_memory"]["action"]) != ACTION_CLASS.get(s["without_memory"]["action"])),
        "memory_fixed": sum(1 for s in steps if s["with_memory"]["agreed"] and not s["without_memory"]["agreed"]),
        "memory_broke": sum(1 for s in steps if not s["with_memory"]["agreed"] and s["without_memory"]["agreed"]),
        "cumulative": cum,
    }


class ReplayRunner:
    def __init__(self, settings: Settings, store: DataStore, agent: Agent):
        self.store = store
        self.agent = agent
        self.memory = MemoryService(replace(settings, hindsight_bank_id=f"{settings.hindsight_bank_id}-replay"))
        self.model = settings.groq_model
        self.task: asyncio.Task | None = None
        self.state = self._load() or {"status": "idle", "steps": [], "total": len(store.replay_invoices())}

    @staticmethod
    def _load() -> dict | None:
        for f in (RESULT_FILE, SAMPLE_FILE):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("status") == "running":  # a run interrupted by a restart
                data["status"] = "interrupted"
            data["source"] = "saved sample" if f == SAMPLE_FILE else "latest run"
            return data
        return None

    def _save(self) -> None:
        try:
            RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
            RESULT_FILE.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        except OSError as e:  # read-only filesystems on serverless hosts
            log.warning("could not save replay result: %s", e)

    def snapshot(self) -> dict:
        return {**self.state, "summary": summarise(self.state.get("steps", []))}

    def start(self) -> bool:
        if self.task and not self.task.done():
            return False
        self.task = asyncio.create_task(self._run())
        return True

    async def _run(self) -> None:
        invoices = self.store.replay_invoices()
        self.state = {"status": "running", "steps": [], "total": len(invoices), "model": self.model,
                      "bank_id": self.memory.bank_id, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "finished_at": None, "error": None, "current": None}
        self._save()
        try:
            await self.memory.reset()
            for n, inv in enumerate(invoices, 1):
                rec = inv["replay"]
                self.state["current"] = {"n": n, "invoice_no": inv["invoice_no"]}
                analysis = run_checks(self.store, inv["id"])
                memory = await self.memory.recall_precedents(analysis, lite=True)
                with_mem = await self.agent.predict(analysis, memory)
                without = await self.agent.predict(analysis, None)
                for arm in (with_mem, without):
                    arm["agreed"] = ACTION_CLASS.get(arm["action"]) == ACTION_CLASS.get(rec["decision"])
                case = build_case(analysis, decision=rec["decision"], reviewer=rec["reviewer"], reason=rec["reason"],
                                  resolved_on=rec["arrived_on"], evidence=rec["evidence"], conditions=rec["conditions"],
                                  source="replay", agent_action=with_mem["action"])
                retained = await self.memory.retain_case(case)
                self.state["steps"].append({
                    "n": n, "invoice_id": inv["id"], "invoice_no": inv["invoice_no"], "arrived_on": rec["arrived_on"],
                    "vendor_name": analysis["vendor"]["name"], "total": inv["total"], "exception_codes": analysis["exception_codes"],
                    "recorded": {"decision": rec["decision"], "reviewer": rec["reviewer"], "reason": rec["reason"]},
                    "with_memory": with_mem, "without_memory": without,
                    "memory": {"precedent_count": memory["precedent_count"], "status": memory["status"],
                               "strength": memory["strength"]["label"],
                               "precedents": [{"case_id": p["case_id"], "relation": p["relation_label"], "decision": p["decision"]}
                                              for p in memory["precedents"]]},
                    "retained_case": retained["case_id"],
                })
                self._save()
                log.info("[replay] %d/%d %s recorded=%s with=%s without=%s precedents=%d", n, len(invoices), inv["invoice_no"],
                         rec["decision"], with_mem["action"], without["action"], memory["precedent_count"])
            self.state["status"] = "done"
        except Exception as e:
            log.exception("replay failed")
            self.state["status"] = "error"
            self.state["error"] = str(e)
        self.state["current"] = None
        self.state["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._save()
