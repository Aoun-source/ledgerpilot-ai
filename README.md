# LedgerPilot AI

**Stops wrong and fraudulent supplier payments before they happen, with evidence a finance clerk can check in ten seconds.**

LedgerPilot is an accounts-payable agent built on **Evolus** and powered by an **open model served with vLLM on an AMD Instinct MI300X** (AMD Developer Cloud, ROCm). It reads the purchase order, the goods-received note and the supplier invoice. It runs a three-way match and fraud checks in plain Python, then lets the agent explain the evidence and route the case: approve, hold, or escalate as possible fraud. Every payment still needs a human yes.

Built for the AMD Developer Hackathon: ACT III, track **Evolus Business Agents on AMD**.

## Why it matters

Accounts-payable teams match invoices by hand. Two things slip through:

- **Overbilling**: a higher unit price than agreed, more units than were delivered, totals that don't add up.
- **Payment diversion**: a perfect-looking invoice that asks for payment to a new bank account, or the same invoice sent twice.

## How it works

| Step | Where it runs | What happens |
| --- | --- | --- |
| 1. Read documents | Evolus **document extractors** (x3) | PO, goods-received note and invoice → JSON with a fixed schema |
| 2. Validate | Python (Pydantic) | Unreadable or missing values become a hold, never a guess |
| 3. Check | Python, `Decimal` maths | Three-way match, arithmetic, vendor master, bank details, duplicates |
| 4. Decide | Evolus **agent** on **Qwen2.5 via vLLM on AMD MI300X** + **knowledge library** | Explains findings, cites the vendor master, proposes a route |
| 5. Act | Evolus **AI Tool** (`email`) + **workflow** | Drafts the supplier query or fraud alert; starts the routing workflow |
| 6. Review | Streamlit review queue + SQLite audit log | A person approves or rejects; every step and execution ID is logged |

**Safety rule:** the model reads and explains; code does every number; the agent can make a case stricter than the rules but never looser. A fraud finding can't be approved by the model.

Evolus building blocks used: document extractors, agent, knowledge library, AI Tool, workflow.

## Run it

### 1. Model on AMD Developer Cloud

Create a 1x MI300X GPU droplet with the **vLLM** Quick Start image, then:

```bash
ssh root@<DROPLET_IP>
docker exec -it rocm /bin/bash
export VLLM_API_KEY=$(openssl rand -hex 32); echo $VLLM_API_KEY
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-32B-Instruct --served-model-name ledgerpilot-model \
  --host 0.0.0.0 --port 8000 --dtype float16 --max-model-len 32768 \
  --api-key $VLLM_API_KEY --enable-auto-tool-choice --tool-call-parser hermes \
  > /tmp/vllm.log 2>&1 &
```

### 2. Evolus workspace

Follow [docs/evolus_setup.md](docs/evolus_setup.md): connect the model, then create the agent, three extractors, the library and the workflow.

### 3. App

```bash
git clone <this repo> && cd ledgerpilot-ai
cp .env.example .env          # fill in your endpoint, keys and IDs
pip install -r requirements.txt
python scripts/make_samples.py   # 20 synthetic cases + vendor master
python scripts/upload_library.py # vendor master -> Evolus library
python scripts/smoke_test.py     # all five checks should PASS
streamlit run app.py
```

Or with Docker:

```bash
cp .env.example .env   # fill it in
docker compose up --build -d   # http://localhost:8501
```

## Tests and evaluation

```bash
python -m pytest -q                      # rules engine + pipeline, offline
python eval/run_eval.py --label "Qwen2.5-32B"     # full live pipeline on 20 cases -> docs/evaluation.md
python scripts/benchmark_amd.py --label "Qwen2.5-32B"   # cost and speed on MI300X -> docs/benchmark.md
```

The 20 synthetic cases cover clean invoices, price variance, short delivery, over-billing, arithmetic errors, items not on the PO, currency mismatch, changed bank account, duplicate and near-duplicate invoices, an unknown look-alike supplier and a corrupt PDF. All data is fictional.

Results: see [docs/evaluation.md](docs/evaluation.md) and [docs/benchmark.md](docs/benchmark.md).

## Project layout

```text
app.py                      Streamlit UI (process, review queue, audit log, results)
src/ledgerpilot/
  schemas.py                Pydantic data contracts, Decimal money
  reconcile.py              three-way match
  fraud.py                  vendor master, bank-detail and duplicate checks
  rules.py                  combines checks; agent can only raise the route
  evolus_client.py          Evolus REST: extractors, workflow, AI Tools, libraries
  agent_client.py           agent via Evolus OpenAI-compatible endpoint; vLLM health check
  pipeline.py               one case end to end, timed and logged
  audit.py                  SQLite audit log
scripts/                    make_samples, smoke_test, upload_library, benchmark_amd
eval/run_eval.py            live evaluation against ground truth
tests/                      offline tests (54)
```

## Limitations

- Line items are matched by SKU; suppliers that print only descriptions need fuzzy matching.
- Duplicate detection looks at invoices processed by this app plus a payment-history file, not a live ERP.
- Synthetic documents are cleaner than real scans; real-world accuracy must be measured on real invoices.

## License

MIT
