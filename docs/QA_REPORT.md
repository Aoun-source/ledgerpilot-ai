# QA report

Date: 16 October 2026. Result: **187 passed, 1 skipped by design, 0 failures** on Windows with Python 3.11.9
(the Docker image's version), after adding cases 21-24 and updating three stale UI tests to the "Ready to pay" stamp.
The per-area counts below are from the 12 October run (143 tests) and were not re-counted.

## What was tested

| Area | Tests | How |
| --- | --- | --- |
| Rules engine | 30 | All 20 sample cases (19 checked here, the corrupt PDF in the pipeline tests): route and finding codes match ground truth; the $200 overcharge and $142.50 short delivery are exact to the cent; the agent can never loosen a route |
| Parsing | 31 | Money formats (1,250.50 / 1.250,50 / 22,5 / $22 / 100 pcs / (200.00)), 10 date formats, numeric IDs, null line lists, currency symbols, IBANs with spaces |
| Reconciliation, fraud, audit, config edge cases | 11 | Quantity split across lines, delivery from another supplier, lines without SKU, duplicate ordering, 30-day window, money-at-risk cap, history exclusions, empty and invalid settings |
| Pipeline with stand-in services | 25 | All 20 cases, agent outage, agent trying to approve fraud, re-processing caught as duplicate, reply parsing |
| Evolus and vLLM clients | 15 | Real HTTP against a local fake: auth headers, file names and MIME types, `useWebhook=false`, retries on 429, giving up on repeated 503, clear messages for 401/402/409, non-JSON replies, unreachable servers, no retry of workflow starts on 5xx, multipart workflow body, email tool payload, library language, vLLM health |
| Full pipeline over real HTTP | 22 | All 20 cases end to end through the real clients; the full bank account is never sent to the model; Evolus outage becomes "needs a person"; an unreadable agent reply falls back to the rules |
| App screens | 10 | Unconfigured start, each of the four decisions, review queue (a blocked payment can't be released without a note), audit filter, clearing history, duplicate on re-check, HTML escaping of document text, results tab |
| Server start | manual | `streamlit run` boots and `/_stcore/health` answers `ok` |

Total: 144 tests, 143 passed, 1 skipped (the corrupt-PDF case in the rules-only suite, covered by the pipeline tests).

## Defects found and fixed

| # | Defect | Impact before the fix | Fix |
| --- | --- | --- | --- |
| 1 | Network errors to Evolus were not caught | A dropped connection crashed the app | All request errors become a clear `EvolusError`; the case is marked "needs a person" |
| 2 | Strict parsing of extractor output | Real invoices with `1.250,50`, `05/10/2026`, `100 pcs`, numeric PO numbers or `"lines": null` failed validation | Lenient, tested parsers for money, dates, IDs and lists; unreadable values become "missing" and are held |
| 3 | Image uploads labelled as PDF | PNG/JPG scans could be rejected by the extractor | MIME type from the file name |
| 4 | Quantity split across invoice lines | 2 x 60 billed against 100 received passed | Quantities checked per item across all lines |
| 5 | Failed and rejected cases counted as payment history | A corrected resubmission was flagged as a duplicate | Only payable cases count as history |
| 6 | Money at risk double counted | Fraud + price findings could exceed the invoice total | Fraud findings cap the figure at the invoice total |
| 7 | Workflow start sent as URL-encoded form | Evolus documents multipart/form-data; live calls could fail | Always multipart |
| 8 | Workflow start retried on 5xx | A retry could start the same workflow twice | Retries only on 429 |
| 9 | Empty values in `.env` | `PRICE_TOLERANCE=` crashed on start | Empty means "use the default"; bad numbers give a clear message |
| 10 | No `.dockerignore` | `.env` with API keys could be copied into the image | `.dockerignore` excludes secrets, databases and git data |
| 11 | Health check not cached | With the AMD endpoint down, every click waited 10 s | Cached for 30 s, 4 s timeout |
| 12 | Document text inserted into HTML unescaped | A crafted invoice could inject markup into the page | Everything from documents or the model is escaped |

## UI changes

- The decision is shown as an ink stamp (Ready to pay, On hold, Payment blocked, Needs a person) with a matching plain-language sentence.
- Findings are written for a finance clerk ("Price above the agreed PO price") with the amount at risk beside each.
- Order, delivery and invoice quantities and prices sit side by side, with mismatches highlighted.
- A "What ran, where" trail shows each step, where it ran (Evolus, the AMD-hosted model or Python) and how long it took.
- Releasing a blocked payment requires a note saying how the supplier was verified.
- A one-line running total: invoices checked, money held, payments blocked.

## Not verified here

- **Live Evolus and AMD services.** Run `python scripts/smoke_test.py` once `.env` is filled in.
- **Docker build.** No Docker daemon in the build environment; the image's steps (install, generate samples, tests) were run on a clean Python 3.11 instead.
- **Pixel-level look in a browser.** Screens were verified programmatically; check the look once by running the app locally.
