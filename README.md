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

## How Hindsight memory is used

| Operation | Where | What it does |
|---|---|---|
| `create_bank` | `backend/app/memory.py` | Creates the team bank with a retain mission (what to extract from a resolution), an observations mission (which patterns to consolidate) and a skeptical reflect mission. |
| `retain` | `POST /api/invoices/{id}/resolve` | Stores the reviewer's resolution as a case note. The note carries the facts that decided it (PO amendment, goods receipt match, amount ratio, bank account), plus metadata (`case_id`, vendor, exception codes, decision, reviewer) and tags (`vendor:V001`, `exc:AMOUNT_SPIKE`, `decision:approve`, `reviewer:priya-nair`). `document_id` is the case id, so a revised resolution replaces the old one. |
| `retain_batch` | `POST /api/memory/seed-history` | Loads six past team cases (price escalation clause, IGST on intra-state supply, duplicate resubmission, missing PO, bank detail fraud, CFO approval). The Shree Ganesh story is deliberately absent so the live demo starts without it. |
| `recall` | `POST /api/invoices/{id}/analyze` | Two tag-scoped passes run in parallel: one filtered to the vendor, one filtered to the exception types on the current invoice. |
| Observations | automatic | Hindsight consolidates repeated resolutions into patterns such as "Shree Ganesh spikes are legitimate when backed by a PO amendment and a matching GRN". These show in the memory panel. |
| `reflect` | "Ask the team memory" box | Free-form questions answered from the bank, for example "what do we know about this vendor?" |

### No invented precedents

A recall on a populated bank almost always returns something, so an empty result is not how "no precedent" is detected. `MemoryService.recall_precedents` groups recalled facts by case and classifies each one in code:

* **Same vendor, same exception**: a direct precedent.
* **Same exception, different vendor**: a related precedent (for example a bank detail fraud at another vendor).
* **Same vendor, different exception**: shown as context, not counted.
* Anything else, including the current invoice's own earlier resolution, is filtered out and listed under "what was sent to Hindsight".

The result is `none`, `single` or `multiple`, and the agent is told which. After the LLM answers, `Agent._validate` removes any cited case id that Hindsight did not return in that run and flags it in the UI.

Only a human resolution is ever retained. The LLM has no tool that writes to memory, so text inside an invoice (for example "previously approved, no need to check") cannot poison the bank.

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
6. Open `VIT/26-27/0104` (bank details changed). The agent recalls the Annapurna Agro fraud case from a different vendor and insists on a call-back.

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

## Tests

```bash
cd backend && ../.venv/Scripts/python -m pytest
```

These are 15 deterministic tests with no network access. They cover a normal invoice, price variance, quantity against PO and GRN, amended PO quantities, duplicates, missing PO, approval tiers, GST head mismatch, MSME terms, bank changes, low amounts, arithmetic, dataset consistency and Indian number formatting. The memory loop is exercised by `scripts/demo_memory_loop.py` against the real services.

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

## Limits

* Invoices are structured data. There is no OCR or PDF ingestion yet.
* Resolution status in the queue is kept in server memory and resets when the server restarts. The memories themselves persist in Hindsight.
* The agent recommends. Nothing here approves or releases a payment.
