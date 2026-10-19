# LedgerPilot FAQ

Short answers to the questions people ask Detective Clerk most often.

## Who are you and what do you do?

I'm Detective Clerk, LedgerPilot's accounts-payable assistant. For every supplier invoice I compare it with the
purchase order and the goods-received note, check the supplier and bank account against the vendor master, look
for duplicates, and explain what I found. I recommend one of three routes: ready to pay, needs review, or payment
blocked. A person always makes the final decision, and I never approve or release a payment myself.

## What is a three-way match?

Before paying an invoice, three documents should agree: the purchase order (what was ordered, at what price), the
goods-received note (what actually arrived) and the supplier invoice (what the supplier asks to be paid). If the
invoice bills more units than arrived, more than were ordered, or a higher price than agreed, the difference is
money at risk and the invoice is held.

## What does invoice fraud look like?

The most common schemes are:

- **Bank-account change (payment diversion):** a real supplier's invoice, but with a new pay-to account, often with
  an urgent email asking to "update our details".
- **Business email compromise:** a criminal writes from or imitates a supplier's or manager's email.
- **Fake or look-alike supplier:** a supplier not in the vendor master, or with a name close to a real one.
- **Duplicate invoice:** the same invoice sent twice, sometimes with a slightly changed number.
- **Overbilling:** a higher price than agreed, units never delivered, or totals that don't add up.

## How do I verify a supplier safely?

Call the supplier on the phone number already in the vendor master, never the number on the invoice or in the email
that asked for a change. Record who you spoke to, when and what they said. A bank-detail change should be approved
by a second person before any payment uses it. If someone pushes for urgency or secrecy, slow down.

## Why was this invoice held?

LedgerPilot holds an invoice for a billing problem: a price above the purchase order, more units than ordered or
received, arithmetic that doesn't add up, tax above the allowed rate, a currency mismatch, or a missing value. The
case page lists each problem with the expected and actual values, and a polite email to the supplier is drafted.

## Why was this payment blocked?

A payment is blocked for a fraud signal: the bank account differs from the vendor master, the supplier is unknown,
or the invoice looks like a duplicate of one already paid. Nothing is paid until a manager verifies the supplier by
phone using the number in the vendor master.

## Can you approve or pay this invoice?

No. I explain and recommend; a person approves in the review queue. I never approve, release or promise a payment,
and I never show a full bank account number.

## How accurate is LedgerPilot?

On 24 synthetic test cases run live: no problem invoice was marked ready to pay, every fraud case was blocked,
routing was 96% accurate and field extraction 99% accurate. A case takes about 45 seconds from upload to decision.

## Which AI model do you run on?

An open model (DeepSeek-V4-Flash by default) served on AMD hardware through AMD Token Factory, or through vLLM on an
AMD Instinct MI300X. I live on the Evolus platform, which also runs the document extractors, my knowledge library,
the supplier-email tool and the routing workflow.

## Does the AI decide the amounts?

No. Every number is computed by plain Python code with exact decimals. I only read, explain and propose a route, and
I can make a case stricter than the rules, never looser.

## What happens if the AI is down?

The rule-based checks still run and their route stands. The case goes to a person with the reason shown, so nothing
is ever approved because the AI was unavailable.

## How do I check an invoice?

Open **Check an invoice**, pick one of the sample cases or upload your own purchase order, delivery note and invoice
as PDFs, and press the check button. The result shows each step, the problems found, my explanation and the drafted
supplier email. The case then waits in the **Review queue**.

## Where is the history of decisions?

In the **Audit log**: every check, its route, who reviewed it, the note they left, and the Evolus run IDs.
