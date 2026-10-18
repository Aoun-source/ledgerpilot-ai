# Paste into the lablab.ai submission form

## Project title
LedgerPilot AI

## Short description
An accounts-payable agent on Evolus and AMD that matches every supplier invoice to its PO and delivery note and stops wrong or fraudulent payments.

## Long description
Accounts-payable teams still match invoices against purchase orders and delivery notes by hand. Two kinds of loss get through: overbilling (a higher price than agreed, units that never arrived, totals that don't add up), and payment diversion, where a perfect-looking invoice asks for payment to a new bank account or arrives twice.

LedgerPilot does the matching and stops those payments before they go out. Evolus document extractors read the PO, the goods-received note and the invoice. Plain Python validates every field and runs the checks with Decimal maths: a three-way match on price and quantity, arithmetic and tax, the vendor master, bank details, PO balance, and exact and look-alike duplicates. An Evolus agent, Detective Clerk, whose model is the open-weight DeepSeek-V4-Flash served on AMD GPUs through AMD Token Factory, explains the evidence, cites the vendor master and proposes a route. An Evolus AI Tool drafts the supplier query or fraud alert, and an Evolus workflow routes the case. A clerk approves or rejects in a review queue, and every step is logged.

The design keeps money safe. Code does every number. The agent can make a decision stricter but never looser, so it cannot approve a fraud finding. When its review doesn't come back, or a value can't be read, the invoice goes to a person with the reason shown. The model never sees the full bank account. Each finding shows its code, the rule that fired and the amount at risk, so a clerk can check it in seconds.

Measured live on 24 synthetic cases: 0 false approvals out of 17 problem invoices, 5 of 5 fraud attempts blocked, 23 of 24 routed correctly, about 45 s from upload to decision.

The repo includes over 200 offline tests, a Docker image built in CI, evaluation and benchmark scripts over 24 synthetic cases (clean invoices, billing errors, fraud attempts and an unreadable PDF), and a demo mode that replays recorded runs, clearly labelled, if the services are down.

## Technology tags
AMD Token Factory, AMD GPUs, DeepSeek-V4-Flash, Evolus, Python, Pydantic, Streamlit, SQLite, Docker, fraud detection, fintech, accounts payable

## Track
Evolus Business Agents on AMD

## Links
- Live app: https://ledgerpilot-ai.streamlit.app
- GitHub: https://github.com/Aoun-source/ledgerpilot-ai

## Cover image
docs/submission/cover.png
