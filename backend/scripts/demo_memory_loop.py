"""Reproducible memory-loop demo against the real Hindsight and Groq APIs.

Uses a separate bank (precedent-demo-run) so it never touches the app's bank.

    python scripts/demo_memory_loop.py

Steps:
  1. Reset the demo bank.
  2. Analyse INV-2001 (Shree Ganesh amount spike). Expect: no precedent.
  3. Reviewer approves it with a reason. Retained into Hindsight.
  4. Analyse INV-2002 (similar spike, PO amended again). Expect: precedent recalled.
  5. Analyse INV-2003 (spike without PO backing). Expect: precedent recalled but judged not applicable.
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

os.environ["HINDSIGHT_BANK_ID"] = os.environ.get("DEMO_BANK_ID", "precedent-demo-run")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def show(label: str, r: dict) -> None:
    m, ag = r["memory"], r["agent"]
    print(f"\n=== {label}: {r['checks']['invoice']['invoice_no']} ({'memory ON' if r['use_memory'] else 'memory OFF'})")
    print("Rule findings:", ", ".join(r["checks"]["exception_codes"]) or "none")
    print(f"Hindsight: status={m.get('status')} precedents={[p['case_id'] + ' [' + p['relation'] + ']' for p in m.get('precedents', [])]}"
          f" raw={m.get('raw_result_count')} gated_out={len(m.get('gated_out', []))}")
    print("Agent headline:", ag.get("headline"))
    print("Precedent assessment:", ag.get("precedent", {}).get("status"), "|",
          textwrap.shorten(ag.get("precedent", {}).get("summary", ""), 300))
    print("Recommendation:", ag.get("recommendation", {}).get("action"), "|",
          textwrap.shorten(ag.get("recommendation", {}).get("rationale", ""), 300))
    print("Memory influence:", ag.get("memory_influence"))
    if r["guardrail_warnings"]:
        print("Guardrail warnings:", r["guardrail_warnings"])
    if r["llm"].get("fallback"):
        print("LLM fallback:", r["llm"]["fallback"])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with TestClient(app) as c:
        cfg = c.get("/api/config").json()
        print("Bank:", cfg["bank_id"], "| model:", cfg["model"], "| configured:", cfg["configured"])
        print("Reset:", c.post("/api/memory/reset").json())

        r1 = c.post("/api/invoices/INV-2001/analyze", json={"use_memory": True}).json()
        show("1. First-time exception", r1)

        res = c.post("/api/invoices/INV-2001/resolve", json={
            "decision": "approve",
            "reviewer": "Priya Nair",
            "reason": "Legitimate bulk order for the festive season. Procurement amended the PO from 1,200 to 2,000 boxes "
                      "before dispatch and stores confirmed all 2,000 boxes on the GRN, so the higher amount is backed by the PO.",
            "evidence": ["PO amendment verified with procurement", "GRN quantity matches invoice"],
        }).json()
        print(f"\n=== 2. Human resolution retained: case {res['case_id']} in {res['memory']['elapsed_ms']} ms")

        r2 = c.post("/api/invoices/INV-2002/analyze", json={"use_memory": True}).json()
        show("3. Similar exception, with memory", r2)

        r3 = c.post("/api/invoices/INV-2003/analyze", json={"use_memory": True}).json()
        show("4. Look-alike exception without PO backing", r3)


if __name__ == "__main__":
    main()
