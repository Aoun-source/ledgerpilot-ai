# LedgerPilot guide

What LedgerPilot is, how it decides, and how to use it. Written for finance clerks and for the Detective Clerk
agent, so it can answer questions about the app accurately.

## What LedgerPilot does

LedgerPilot stops wrong and fraudulent supplier payments before they happen. For each supplier invoice it reads
three documents (purchase order, goods-received note, invoice), checks that they agree, checks the supplier and
bank account against the vendor master, and looks for duplicates. It then routes the case and explains why, with
evidence a clerk can verify in about ten seconds.

LedgerPilot never pays or approves anything by itself. Every case waits for a person in the review queue, and every
step is written to the audit log.

## How a case is checked

| Step | Where it runs | What happens |
| --- | --- | --- |
| 1. Read the documents | Evolus document extractors (one each for PO, goods-received note, invoice) | Each PDF becomes JSON with fixed field names |
| 2. Validate | Python (Pydantic) | A missing or unreadable value becomes a hold, never a guess |
| 3. Check | Python with exact decimal maths | Three-way match, arithmetic, vendor master, bank details, duplicates |
| 4. Explain | Detective Clerk, an Evolus agent on an open model on AMD | Explains the findings, cites the vendor master, proposes a route |
| 5. Act | Evolus AI Tool (email) and an Evolus workflow | Drafts the supplier query or fraud alert and starts the routing workflow |
| 6. Review | LedgerPilot review queue and audit log | A person approves or rejects; every step and Evolus run ID is logged |

Safety rule: the model reads and explains, code does every number. The agent may make a case stricter than the
rules, never looser. A fraud finding can never be approved by the model. If the agent is slow or unreachable, the
rule-based route stands and the case goes to a person.

## The three routes

- **Ready to pay** (`approve_for_payment`): the three documents agree and the supplier and bank account match the
  vendor master. A person still gives the final approval.
- **Needs review** (`hold_for_review`): a billing problem such as price, quantity, arithmetic, missing data or
  currency. The payment is held and a polite query to the supplier is drafted.
- **Payment blocked** (`escalate_fraud`): a fraud signal such as a bank-account mismatch, an unknown supplier or a
  duplicate invoice. Nothing is paid until a manager verifies the supplier by phone, using the number already in
  the vendor master.

## Every check and what it means

Billing problems (route: needs review)

| Code | Meaning |
| --- | --- |
| PRICE_VARIANCE | The invoice unit price is higher than the price agreed on the purchase order |
| QTY_OVER_PO | The invoice bills more units than were ordered |
| QTY_NOT_RECEIVED | The invoice bills more units than the goods-received note says arrived |
| ITEM_NOT_ON_PO | The invoice bills an item that is not on the purchase order |
| PO_PRICE_AMBIGUOUS | The purchase order lists the same item at different prices |
| LINE_ARITHMETIC | A line total is not quantity times unit price |
| SUBTOTAL_ARITHMETIC | The subtotal is not the sum of the lines |
| TOTAL_ARITHMETIC | The total is not subtotal plus tax |
| TAX_OUT_OF_RANGE | Tax is above the allowed share of the subtotal (30% by default) |
| CURRENCY_MISMATCH | The currency differs between the invoice, the PO or the vendor master |
| MISSING_FIELD | A required value is missing or unreadable |
| NEGATIVE_VALUE | A quantity, price or total is negative |
| PO_MISMATCH / GRN_PO_MISMATCH | The documents refer to different purchase orders |
| SUPPLIER_MISMATCH / GRN_SUPPLIER_MISMATCH | The documents name different suppliers |
| PO_ALREADY_BILLED | Earlier invoices already billed some of the ordered units, and this one bills more than are left |
| BANK_MISSING | The invoice has no pay-to bank account |

Fraud signals (route: payment blocked)

| Code | Meaning |
| --- | --- |
| BANK_MISMATCH | The pay-to account on the invoice differs from the account in the vendor master |
| UNKNOWN_VENDOR | The supplier is not in the vendor master |
| DUPLICATE_INVOICE | An invoice with this number from this supplier was already paid |
| LOOKALIKE_INVOICE_NUMBER | The number is a near copy of a paid one (an added letter, dash or space) |
| POSSIBLE_DUPLICATE | Same supplier and same amount as a recent paid invoice |

Hand-off to a person

| Code | Meaning |
| --- | --- |
| LOW_CONFIDENCE | The agent's review could not be read, so a person decides |
| AGENT_CONCERN | The agent chose a stricter route than the rules; a person decides |

"Money at risk" is the amount the checks say should not be paid, for example the overbilled part of a line, or the
whole invoice for a fraud signal.

## The pages in the app

- **Overview:** totals for invoices checked, ready to pay, needs review and payments blocked, plus a shortcut to
  ask the agent.
- **Check an invoice:** pick one of the 24 rehearsed sample cases, or upload your own purchase order, delivery note
  and invoice (PDF). The page shows each step with its timing, the discrepancies, the agent's explanation and
  evidence, and the drafted supplier email.
- **Ask the agent:** chat with Detective Clerk about invoices, fraud and how LedgerPilot works.
- **Review queue:** every case waiting for a person. Approve or reject; a blocked payment needs a note saying how
  the supplier was verified.
- **Audit log:** every check, its decision, who reviewed it, and the Evolus run IDs behind it.
- **Results:** accuracy, fraud caught and speed, measured live on the 24 synthetic cases.
- **Settings:** connection status, a model speed test, team usage on AMD Token Factory, and demo data.

**Replay recorded runs** (sidebar switch) replays saved outputs of real live runs, so the app can be shown without
using the team's shared model quota.

## Results on the 24 synthetic cases

Measured with the live services (Evolus extractors, Python rules, the agent on AMD Token Factory):

- 0 of 17 problem cases marked ready to pay (no false approvals)
- 100% of fraud cases escalated as fraud
- 96% routing accuracy; 99% field extraction accuracy
- about 45 seconds median from upload to decision; about 20 seconds median for the agent

## Technology

- **Evolus** (evolus.ai): document extractors, the Detective Clerk agent, the knowledge library "Vendor master and
  AP policy", the AI Tool for supplier emails, and the "Exception routing" workflow.
- **AMD:** the agent runs on an open model (DeepSeek-V4-Flash by default) served by AMD Token Factory on AMD
  Radeon Cloud, or by vLLM on an AMD Instinct MI300X on AMD Developer Cloud.
- **Python:** all money maths uses exact decimals; rules are plain code anyone can read.
- **Streamlit:** the web app. **SQLite:** the audit log.

## Privacy and safety

- The agent never sees a full bank account number: accounts are masked to the last four characters everywhere in
  the app.
- Only synthetic sample data is sent to the shared AMD model, never real invoices.
- Text inside documents is treated as data, never as instructions to the agent.
- The agent never approves, releases or promises a payment, in a case or in chat.
