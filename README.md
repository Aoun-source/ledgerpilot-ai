# LedgerPilot AI

**Stops wrong and fraudulent supplier payments before they happen, with evidence a finance clerk can check in ten seconds.**

LedgerPilot is an accounts-payable agent built on **Evolus** and powered by an **open model on AMD GPUs**: by default through **[AMD Token Factory](https://notebooks.amd.com/tokenfactory)** (AMD Radeon Cloud's free model API), or served with vLLM on your own AMD Instinct MI300X (AMD Developer Cloud, ROCm). It reads the purchase order, the goods-received note and the supplier invoice. It runs a three-way match and fraud checks in plain Python, then lets the agent explain the evidence and route the case: approve, hold, or escalate as possible fraud. Every payment still needs a human yes.

Built for the AMD Developer Hackathon: ACT III, track **Evolus Business Agents on AMD**.

**Live app:** [ledgerpilot-ai.streamlit.app](https://ledgerpilot-ai.streamlit.app) · **Demo video:** [docs/submission/LedgerPilot_demo.mp4](docs/submission/LedgerPilot_demo.mp4) · **Slides:** [docs/submission/LedgerPilot_pitch.pdf](docs/submission/LedgerPilot_pitch.pdf)

The hosted app holds no API keys, so it shows its connection notes until you run it with your own `.env` (see Run it).

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
| 4. Decide | Evolus **agent** on an **open model on AMD** (Token Factory, or vLLM on MI300X) + **knowledge library** | Explains findings, cites the vendor master, proposes a route |
| 5. Act | Evolus **AI Tool** (`email`) + **workflow** | Drafts the supplier query or fraud alert; starts the routing workflow |
| 6. Review | Streamlit review queue + SQLite audit log | A person approves or rejects; every step and execution ID is logged |

**Safety rule:** the model reads and explains; code does every number; the agent can make a case stricter than the rules but never looser. A fraud finding can't be approved by the model. A clean invoice is only marked ready to pay when the checks and a readable agent review agree; otherwise it goes to a person with the reason shown.

Evolus building blocks used: document extractors, agent, knowledge library, AI Tool, workflow.

**Talk to the agent.** Outside the app, the same agent (Detective Clerk) answers people in the Evolus chat or
through Evolus's OpenAI-compatible endpoint: it explains what it does, what a three-way match is, the common
invoice-fraud schemes and how to verify a supplier safely, using the vendor master and the AP fraud guide
(`data/ap_fraud_guide.md`) in its knowledge library. It never approves or promises a payment in chat.

## Run it

### 1. Model on AMD

**Option A: AMD Token Factory (default, free, nothing to host).**

| What | Value |
| --- | --- |
| Sign in and get the team key | <https://notebooks.amd.com/tokenfactory> (AMD AI Developer Program account) |
| API base URL | `https://developer.amd.com.cn/radeon/api/v1` |
| Key | `rc-` + 48 hex characters, one per team |
| Default model | `DeepSeek-V4-Flash` (free, supports tool calls, doesn't think unless asked) |

1. Every teammate signs in and clicks **Redeem API Key**. The key appears only after **all** of you have redeemed.
2. Click **Copy to clipboard** and put the key in `.env` as `AMD_API_KEY`. That is all the app needs.
3. Check it (PowerShell: use `curl.exe`):

```bash
curl https://developer.amd.com.cn/radeon/api/v1/models -H "Authorization: Bearer rc-..."
```

Things to know:

- **Shared limits.** The whole team shares one key: about 30 requests a minute per key, 20 per account,
  8 at once, and a daily spend cap. Evolus, the app, the smoke test and the benchmark all count. Don't
  run evaluations at the same time as a teammate. Check what's left with the app's **Check team usage** button.
- **Synthetic data only.** Token Factory's terms say not to send sensitive personal or financial data, and
  prompts are kept for about 2 days. Use the fictional cases in `data/samples`, never real invoices.
- **The catalog changes.** If a model starts returning 400 "not supported", list `/v1/models` and set `AMD_MODEL`.
- **Thinking models** (MiMo, GLM, Qwen3.8-27B) spend part of `max_tokens` thinking and can return empty
  replies. Stay with DeepSeek-V4-Flash, or set `AMD_REASONING_EFFORT=low`.
- **Track rules.** If your hackathon track requires the model on *your own* vLLM endpoint on AMD Developer
  Cloud, use Option B for the submission.

**Option B: your own vLLM server on AMD Developer Cloud.**
Create a 1x MI300X GPU droplet with the **vLLM** Quick Start image, then:

```bash
ssh root@<DROPLET_IP>
docker exec -it rocm /bin/bash
export VLLM_API_KEY=$(openssl rand -hex 32); echo $VLLM_API_KEY
nohup python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-32B-Instruct --served-model-name ledgerpilot-model \
  --host 0.0.0.0 --port 8000 --dtype float16 --max-model-len 32768 \
  --api-key $VLLM_API_KEY --enable-auto-tool-choice --tool-call-parser hermes \
  > /tmp/vllm.log 2>&1 &
```

`nohup` keeps the server running after you close the SSH window. Working from Windows with no Linux
machine? Everything above runs on the droplet; see [docs/setup_windows.md](docs/setup_windows.md).
Then set `AMD_BASE_URL=http://<DROPLET_IP>:8000/v1`, `AMD_API_KEY` (your `--api-key`) and
`AMD_MODEL=ledgerpilot-model` in `.env`.

### 2. Evolus workspace

Follow [docs/evolus_setup.md](docs/evolus_setup.md): connect the model, then create the agent, three extractors, the library and the workflow.

### 3. App

Needs Python 3.10 or newer (the Docker image uses 3.11).

```bash
git clone https://github.com/Aoun-source/ledgerpilot-ai.git
cd ledgerpilot-ai
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env  -- then fill it in
python -m pytest -q                # offline tests, no keys needed
python scripts/upload_library.py   # vendor master -> Evolus library (needs keys)
python scripts/smoke_test.py       # live check: all five lines should say PASS
streamlit run app.py               # http://localhost:8501
```

The sample cases ship with the repo; `python scripts/make_samples.py` regenerates them.
Without a filled-in `.env` the app still opens and says exactly which settings are missing.

Or with Docker:

```bash
cp .env.example .env               # fill it in
docker compose up --build -d       # http://localhost:8501
```

### Settings (`.env`)

| Variable | Required | What it is |
| --- | --- | --- |
| `AMD_API_KEY` | for the model badge, speed test, usage check and benchmark | your team's Token Factory key (`rc-...`), or your vLLM `--api-key` |
| `AMD_BASE_URL` | no (default Token Factory) | `https://developer.amd.com.cn/radeon/api/v1`, or `http://<DROPLET_IP>:8000/v1` for your own vLLM |
| `AMD_MODEL` | no (default `DeepSeek-V4-Flash` on Token Factory, `ledgerpilot-model` on vLLM) | model name; must match the model your Evolus agent uses |
| `AMD_REASONING_EFFORT` | no | `none`, `low`, `medium`, `high`: turns thinking down on models that think by default |
| `EVOLUS_API_KEY`, `EVOLUS_APP_ID` | yes | Evolus API key and space (application) ID |
| `EVOLUS_AGENT_ID` | yes | the Detective Clerk agent (instructions in `src/ledgerpilot/agent_client.py`) |
| `EVOLUS_EXTRACTOR_INVOICE_ID`, `EVOLUS_EXTRACTOR_PO_ID`, `EVOLUS_EXTRACTOR_GRN_ID` | yes | the three document extractors |
| `EVOLUS_EXTRACTOR_AGENT_ID` | no | agent that owns the extractors, if not the Clerk |
| `EVOLUS_WORKFLOW_ID` | no | "Exception routing" workflow; skipped when empty |
| `EVOLUS_LIBRARY_ID` | for `upload_library.py` | "Vendor master and AP policy" library |
| `PRICE_TOLERANCE`, `MAX_TAX_RATE` | no | business rules, defaults `0.00` and `0.30` |
| `EVOLUS_TIMEOUT`, `AGENT_TIMEOUT` | no | seconds before a slow call hands the case to a person, default `90` |
| `RECORDINGS_DIR` | no | where demo-mode recordings live, default `data/recordings` |

The older names `VLLM_BASE_URL`, `VLLM_API_KEY` and `VLLM_MODEL` still work; the `AMD_*` names win when both are set.

### Demo mode

For judging when the live services are slow or down. `python eval/run_eval.py` saves each case's
**live** output to `data/recordings/`, and after any live check in the app, **Save for demo mode** does
the same for that case. Switching on **Demo mode** in the sidebar then replays those outputs. Every replayed
screen carries a "Recorded run" banner with the time and model it was recorded with. Replays never call
Evolus or the model and are never added to the review queue or audit log.

Links for the demo (replace the host with yours):

- `http://localhost:8501/?case=case_07` opens and checks case 07 live
- `http://localhost:8501/?demo=1&case=case_15` opens demo mode and replays case 15

The three rehearsal cases also have one-click buttons at the top of the page:
case 01 (ready to pay), case 07 (needs review, $200 over the PO price) and case 15 (payment blocked, bank account changed).

## Tests and evaluation

```bash
python -m pytest -q                                     # offline, about a minute
python eval/run_eval.py --label "DeepSeek-V4-Flash"           # live pipeline on all cases -> docs/evaluation.md
python scripts/benchmark_amd.py --label "DeepSeek-V4-Flash"   # latency and tokens per invoice -> docs/benchmark.md
```

On Token Factory the benchmark paces itself to 10 requests a minute (half the shared limit, so teammates
aren't throttled) and at most 8 at once; 12 requests at two concurrency levels take about 2.5 minutes.
On your own vLLM droplet it measures throughput and cost instead: add `--requests 40 --concurrency 1 4 16 --gpu-price <USD per GPU-hour>`.

The 24 synthetic cases cover clean invoices, price variance, short delivery, over-billing, arithmetic errors, items not on the PO, currency mismatch, changed bank account, duplicate and near-duplicate invoices, a look-alike invoice number, padded tax, a credit note sent as an invoice, a PO billed twice, an unknown look-alike supplier and a corrupt PDF. All data is fictional.

Results: the two commands above write `docs/evaluation.md` and `docs/benchmark.md` from a live run; they also appear on the app's Results page.

## Project layout

```text
app.py                      Streamlit UI (process, review queue, audit log, results)
src/ledgerpilot/
  schemas.py                Pydantic data contracts, Decimal money
  reconcile.py              three-way match
  fraud.py                  vendor master, bank-detail and duplicate checks
  rules.py                  combines checks; agent can only raise the route
  evolus_client.py          Evolus REST: extractors, workflow, AI Tools, libraries
  agent_client.py           agent via Evolus OpenAI-compatible endpoint; AMD model health, speed and usage checks
  pipeline.py               one case end to end, timed and logged
  audit.py                  SQLite audit log
  recording.py              save and replay live runs for demo mode
scripts/                    make_samples, smoke_test, upload_library, benchmark_amd
eval/run_eval.py            live evaluation against ground truth
tests/                      offline tests: rules, edge cases, real HTTP against a local
                            fake of Evolus and the AMD model endpoint, and a click-through of every app screen
```

## Submission assets

`docs/submission/`: demo video script, project descriptions and tags, the cover image
(`python scripts/make_cover.py`) and the submission checklist.

## Quality checks

See [docs/QA_REPORT.md](docs/QA_REPORT.md) for what was tested and what was fixed.

## Limitations

- Line items are matched by SKU; suppliers that print only descriptions need fuzzy matching.
- Duplicate detection looks at invoices processed by this app plus a payment-history file, not a live ERP.
- Synthetic documents are cleaner than real scans; real-world accuracy must be measured on real invoices.

## License

MIT
