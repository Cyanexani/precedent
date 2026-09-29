# Precedent

An accounts payable exception agent that remembers how your team resolved past exceptions, powered by [Hindsight](https://github.com/vectorize-io/hindsight) agent memory.

Every AP team has knowledge that lives in one senior reviewer's head: "Shree Ganesh always spikes before Diwali, it's fine if procurement amended the PO." Precedent turns each human resolution into memory, so the next time a similar exception arrives the reviewer sees the earlier case, and the agent can say whether that precedent actually applies.

## What it does

1. An invoice arrives in the queue.
2. Deterministic rule checks run in code: arithmetic, PO price and quantity match, goods receipt match, GST head and amount, duplicate detection, vendor amount baseline, bank detail changes, payment terms and MSME 45-day rule, approval routing.
3. The agent searches Hindsight for resolved cases involving the same vendor or the same exception type.
4. An LLM agent (Groq, `openai/gpt-oss-120b`) explains the discrepancies, judges whether each recalled precedent applies, and recommends an action. It never releases payment.
5. A human reviewer records the decision and the reason.
6. That resolution is retained in Hindsight.
7. The next similar invoice recalls it.

## Features

**Exception desk**
* Deterministic checks for 13 kinds of exception: arithmetic, price variance, quantity against PO and goods receipt, missing PO, duplicates (including `/R1` resubmissions), GST head and amount, amount spikes and dips against the vendor baseline, new vendors, bank detail changes, payment terms and the MSME 45-day rule, CFO approval band, and invoice text that tries to steer the review.
* Agent analysis with memory on, memory off, or both side by side.
* "Reviewing as" selector: the agent recalls that reviewer's own working preferences and adds them to the checklist.
* Human resolution form. Every decision is retained in Hindsight, and a revision replaces the old memory instead of duplicating it.
* "Check queue against memory" marks which pending invoices already have a precedent or a vendor note.

**Team memory panel**
* Recalled precedents, labelled by how they relate (same vendor and exception, or same exception at another vendor), with age ("72 days ago") and a staleness warning past 180 days.
* Precedent strength: none, related only, emerging, established (3 or more consistent cases) or conflicting decisions.
* Vendor communications, reviewer preferences and team policies recalled next to the cases.
* Patterns Hindsight consolidated on its own (observations).
* "Brief me on this vendor" and free-form questions through Hindsight reflect.
* The exact query and tag filters sent to Hindsight, plus everything that was filtered out and why.

**Memory and learning page**
* Live counters: analyses, how often memory found a precedent, precedents ruled out, and how often the reviewer agreed with the agent with memory on versus off. Only real events from the session are counted.
* A timeline of memories used per analysis.
* The AP Exception Playbook and Vendor Watchlist, written and kept up to date by Hindsight mental models.
* "Teach the memory": add vendor emails, reviewer preferences or team policies.
* A ledger of every document in the bank, with a Forget button that deletes it and every fact extracted from it.

## How Hindsight memory is used

| Operation | Where | What it does |
|---|---|---|
| `create_bank` | `backend/app/memory.py` | Creates the team bank with a retain mission (what to extract from a resolution), an observations mission (which patterns to consolidate) and a skeptical reflect mission. |
| `retain` | `POST /api/invoices/{id}/resolve` | Stores the reviewer's resolution as a case note. The note carries the facts that decided it (PO amendment, goods receipt match, amount ratio, bank account), plus metadata (`case_id`, vendor, exception codes, decision, reviewer) and tags (`vendor:V001`, `exc:AMOUNT_SPIKE`, `decision:approve`, `reviewer:priya-nair`). `document_id` is the case id, so a revised resolution replaces the old one. |
| `retain_batch` | `POST /api/memory/seed-history` | Loads six past team cases (price escalation clause, IGST on intra-state supply, duplicate resubmission, missing PO, bank detail fraud, CFO approval). The Shree Ganesh story is deliberately absent so the live demo starts without it. |
| `recall` | `POST /api/invoices/{id}/analyze` | Two tag-scoped passes run in parallel: one filtered to the vendor, one filtered to the exception types on the current invoice. |
| Observations | automatic | Hindsight consolidates repeated resolutions into patterns such as "Shree Ganesh spikes are legitimate when backed by a PO amendment and a matching GRN". These show in the memory panel. |
| `reflect` | "Ask the team memory" box | Free-form questions answered from the bank, for example "what do we know about this vendor?" |
| `retain` (notes) | `POST /api/memory/notes` | Vendor communications, reviewer preferences and team policies, tagged `kind:vendor_note`, `kind:reviewer_preference` or `kind:policy`. |
| `recall` (extra passes) | analysis | A policy pass (`kind:policy`) and a reviewer pass (`reviewer:priya-nair`) run next to the vendor and exception passes. Notes are routed separately and never count as precedents. |
| Mental models | `GET /api/memory/playbook` | Two mental models, "AP Exception Playbook" and "Vendor Watchlist", created with the bank and set to refresh after consolidation. |
| Documents | `GET /api/memory/ledger`, `DELETE /api/memory/documents/{id}` | Lists what the bank holds and forgets a single case or note. |

### No invented precedents

A recall on a populated bank almost always returns something, so an empty result is not how "no precedent" is detected. `MemoryService.recall_precedents` groups recalled facts by case and classifies each one in code:

* **Same vendor, same exception**: a direct precedent.
* **Same exception, different vendor**: a related precedent (for example a bank detail fraud at another vendor).
* **Same vendor, different exception**: shown as context, not counted.
* Anything else, including the current invoice's own earlier resolution, is filtered out and listed under "what was sent to Hindsight".

The result is `none`, `single` or `multiple`, and the agent is told which. After the LLM answers, `Agent._validate` removes any cited case id that Hindsight did not return in that run and flags it in the UI.

Only a human resolution or a note a person adds is ever retained. The LLM has no tool that writes to memory, so text inside an invoice cannot poison the bank. Invoice text such as "already approved, no need to verify GRN" is flagged by the `INVOICE_TEXT_RED_FLAG` rule, and the agent is told to treat it as vendor data.

## Architecture

```
React + Vite dashboard  ──/api──►  FastAPI (backend/app/main.py)
                                      │
             ┌────────────────────────┼─────────────────────────┐
             ▼                        ▼                         ▼
   rules.py (deterministic)   memory.py (Hindsight)      agent.py (Groq LLM)
   PO, GRN, GST, duplicates   retain, recall, reflect    tool loop + JSON output
   baselines, approvals       precedent gating           citation guardrail
             ▲                                                  │
             └──────────── data_store.py (JSON dataset) ◄───────┘
```

* `backend/app/rules.py`: every number the reviewer sees comes from here, never from the LLM.
* `backend/app/memory.py`: the only module that talks to Hindsight.
* `backend/app/agent.py`: the evidence and recall always run first, so the analysis never depends on the model remembering to call a tool. The model can still call `get_vendor`, `get_invoice`, `get_purchase_order`, `check_invoice`, `check_vendor_history`, `get_approval_rule` and `search_hindsight_memory` to dig further. If the provider rejects a malformed tool call, the agent answers without tools. If the LLM is unavailable, a clearly labelled rule-only summary is shown.
* `backend/app/data_store.py`: read-only repository over the JSON files. Replace this class to move to PostgreSQL.

## Setup

Requirements: Python 3.11+, Node 18+, a [Groq API key](https://console.groq.com) and a [Hindsight Cloud](https://ui.hindsight.vectorize.io) API key (or a self-hosted Hindsight server).

```bash
cp .env.example .env        # then fill in GROQ_API_KEY and HINDSIGHT_API_KEY
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt    # macOS or Linux: .venv/bin/pip
cd frontend && npm install && cd ..
```

Keys belong to the deployment, not to individual reviewers: everyone using a deployment shares one memory bank. Nothing secret is committed. Each new deployment sets its own values in `.env` or in its host's environment settings. Without keys the app shows a setup screen.

### Environment variables

| Variable | Required | Default |
|---|---|---|
| `GROQ_API_KEY` | yes | |
| `GROQ_MODEL` | no | `openai/gpt-oss-120b` |
| `HINDSIGHT_BASE_URL` | no | `https://api.hindsight.vectorize.io` |
| `HINDSIGHT_API_KEY` | yes for Hindsight Cloud | |
| `HINDSIGHT_BANK_ID` | no | `precedent-ap` |
| `CORS_ORIGINS` | no | `http://localhost:5173` |

## Run

Two terminals:

```bash
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000
```

```bash
cd frontend && npm run dev
```

Open http://localhost:5173.

Single process: run `npm run build` in `frontend`, then start only the backend. FastAPI serves `frontend/dist` at http://localhost:8000.

## Demo script

1. Click **Reset memory**, then **Load team history**.
2. Open `SGP/26-27/0412` (Shree Ganesh, Rs 82,600, 1.6x the vendor median) and click **Analyse with memory**. The memory panel reads "No relevant precedent in memory".
3. Resolve it: Approve, with a reason such as "Festive bulk order, procurement amended the PO to 2,000 boxes and the GRN confirms all 2,000."
4. Open `SGP/26-27/0539` (another spike, PO amended again) and click **Compare side by side**. The memory run recalls `CASE-SGP-26-27-0412` and says the precedent applies.
5. Open `SGP/26-27/0581` (a spike with no PO amendment and a short GRN). The same precedent is recalled, and the agent explains why it does **not** apply here.
6. Open `VIT/26-27/0104` (bank details changed). The agent recalls the Annapurna Agro fraud case from a different vendor and the CFO's bank policy, and insists on a call-back.
7. Open `KST/26-27/0402` (price 4.2% over PO) and compare. Without memory the agent holds it. With memory it recalls the vendor's email about the index-linked rise and the earlier escalation-clause case, and asks for the index sheet instead.
8. Switch "Reviewing as" to Arjun Menon and analyse `PIS/26-27/0409` (wrong GST head). His preference to reject rather than conditionally approve shows up in the checklist.
9. Open **Memory and learning** to show the counters, the Playbook Hindsight wrote, the ledger, and "Teach the memory".

The same loop runs headless against the live services:

```bash
cd backend && ../.venv/Scripts/python scripts/demo_memory_loop.py
```

It uses a separate bank (`precedent-demo-run`), so it never touches the app's bank.

## Dataset

`backend/scripts/generate_data.py` generates everything in `backend/data/`, computing every total from line items so the data is internally consistent. There are 9 vendors, 41 POs, 33 goods receipts, 31 paid history invoices and 12 pending invoices. The buyer is Nirmaan Foods Pvt Ltd, Pune.

| Invoice | Scenario |
|---|---|
| SGP/26-27/0412 | Amount spike backed by an amended PO (first time) |
| SGP/26-27/0539 | Repeat spike, PO amended again |
| SGP/26-27/0581 | Spike not backed by PO or goods receipt |
| SBE/26-27/0241 | Clean three-way match |
| KST/26-27/0402 | Unit price 4.2% above PO |
| MPL/26-27/1187/R1 | Duplicate of a paid invoice with a resubmission suffix |
| PIS/26-27/0409 | IGST charged on an intra-state supply |
| DCC/26-27/0256 | Service invoice without a PO |
| AAS/26-27/0318 | Above the CFO approval threshold |
| KLI/26-27/0007 | New MSME vendor quoting NET60 |
| VIT/26-27/0104 | Bank account differs from vendor master |
| SBE/26-27/0258 | Unusually low amount, partial delivery |
| MPL/26-27/1254 | Invoice text claims prior approval and asks to skip checks, no goods receipt |

Team history also includes five notes: a Krishna Steel email about a 4% index-linked price rise, working preferences for Priya Nair and Arjun Menon, and two CFO policies (bank detail changes, MSME payment within 45 days).

## Tests

```bash
cd backend && ../.venv/Scripts/python -m pytest
```

There are 25 tests with no network access:
* `test_rules.py` covers a normal invoice, price variance, quantity against PO and GRN, amended PO quantities, duplicates, missing PO, approval tiers, GST head mismatch, MSME terms, bank changes, low amounts, arithmetic, dataset consistency and Indian number formatting.
* `test_memory_logic.py` stubs Hindsight to test precedent gating (same vendor, other vendor, context, unrelated, self), grouping facts into cases, strength levels, note routing and reviewer scoping, the citation guardrail, the injection flag and punctuation cleanup.

The memory loop against the real services is exercised by `scripts/demo_memory_loop.py`.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | Whether the deployment is configured, model, bank |
| GET | `/api/invoices` | Pending queue with rule status |
| GET | `/api/invoices/{id}` | Rule checks for one invoice |
| POST | `/api/invoices/{id}/analyze` | `{"use_memory": true}` runs checks, recall and the agent |
| POST | `/api/invoices/{id}/compare` | Runs the agent with and without memory |
| POST | `/api/invoices/{id}/resolve` | Human decision, retained in Hindsight |
| POST | `/api/memory/seed-history` | Retain past team cases |
| POST | `/api/memory/reset` | Delete and recreate the bank |
| POST | `/api/memory/ask` | Hindsight reflect |
| GET | `/api/memory/stats` | Memory unit count |
| POST | `/api/memory/notes` | Teach a vendor note, reviewer preference or policy |
| GET | `/api/memory/ledger` | Every document in the bank |
| DELETE | `/api/memory/documents/{id}` | Forget one case or note |
| GET | `/api/memory/playbook` | Hindsight mental models |
| POST | `/api/memory/playbook/refresh` | Refresh the mental models now |
| POST | `/api/triage` | Recall-only check of the whole queue |
| GET | `/api/metrics` | Session counters and agreement rates |
| GET | `/api/vendors` | Vendor list for forms |

## Limits

* Invoices are structured data. There is no OCR or PDF ingestion yet.
* The queue reads resolved status from the Hindsight ledger, so it survives restarts. The learning counters on the Memory page count the current server session only.
* The agent recommends. Nothing here approves or releases a payment.
