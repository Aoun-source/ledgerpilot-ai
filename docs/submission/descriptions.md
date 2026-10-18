# Project descriptions and tags

Numbers come from `docs/evaluation.md` (live run, 18 October 2026). If a field on
the submission form has a character limit, use the short description there.

Written for the default setup, the agent's model on **AMD Token Factory**. If you ran the agent on your
own vLLM droplet instead, describe Qwen2.5 served with vLLM on an AMD Instinct MI300X, use the
throughput and cost row of `docs/benchmark.md`, and put MI300X, ROCm and vLLM back in the tags.

## Name

LedgerPilot AI

## Short description (one sentence, 147 characters)

An accounts-payable agent on Evolus and AMD that matches every supplier invoice to its PO and
delivery note and stops wrong or fraudulent payments.

## Long description

Accounts-payable teams still match invoices against purchase orders and delivery notes by hand. Two
kinds of loss get through: overbilling (a higher price than agreed, units that never arrived, totals
that don't add up), and payment diversion, where a perfect-looking invoice asks for payment to a new
bank account or arrives twice.

LedgerPilot does the matching and stops those payments before they go out. Three Evolus document
extractors read the PO, the goods-received note and the invoice. Plain Python validates every field
and runs the checks with Decimal maths: a three-way match on price and quantity, arithmetic and tax,
the vendor master, bank details, PO balance, and exact and look-alike duplicates. An Evolus agent,
whose model is the open-weight DeepSeek-V4-Flash served on AMD GPUs through AMD Token Factory, explains the
evidence, cites the vendor master from an Evolus knowledge library and proposes a route. An Evolus AI
Tool drafts the supplier query or fraud alert, and an Evolus workflow routes the case. A clerk approves
or rejects in a review queue, and every step is logged.

The design keeps money safe. Code does every number. The agent can make a decision stricter but
never looser, so it cannot approve a fraud finding. When its review doesn't come back, or a value can't
be read, the invoice goes to a person with the reason shown. The model never sees the full bank
account. Each finding shows its code, the rule that fired and the amount at risk, so a clerk can check
it in seconds.

We measured it live on 24 synthetic cases (7 clean, 11 billing errors, 5 fraud attempts, 1 unreadable
PDF): 0 false approvals out of 17 problem invoices, 5 of 5 fraud attempts blocked, and 23 of 24 (96%)
routed correctly, with a median of 45 s from upload to decision. On AMD Token Factory the agent step
answers in a median of 20 s. The one miss was a clean invoice held for a person, never paid.

The repo includes over 200 offline tests, a Docker image built in CI, the evaluation and benchmark
scripts, and a demo mode that replays recorded live runs, clearly labelled, if the services are down.

## Technology tags

AMD Token Factory · AMD Radeon Cloud · AMD GPUs · DeepSeek-V4-Flash · open-weight LLM · Evolus · Evolus
agents · document extraction · knowledge library · AI Tools · workflows · Python · Pydantic · Streamlit ·
SQLite · Docker · GitHub Actions · accounts payable · invoice processing · fraud detection · fintech ·
human in the loop

## Track

Evolus Business Agents on AMD
