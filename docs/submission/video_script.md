# Demo video script (3 minutes)

About 360 spoken words: roughly 2 minutes 40 at a calm pace, leaving room for the clicks. Brackets `[__]` are numbers to copy from `docs/evaluation.md` and
`docs/benchmark.md` after the live run. Never round them up, and cut a line rather than guess.
The tag after each scene names the judging criterion it serves. Written for the agent's model on AMD
Token Factory; if you used your own vLLM droplet, say Qwen2.5 with vLLM on an AMD Instinct MI300X instead.

**Before recording:** run `python scripts/smoke_test.py` (all PASS), click **Clear demo history** in the
sidebar, and open the app at 1280×720 or larger. If the live services are slow, record with
`?demo=1` and keep the "Recorded run" banner in shot; say "recorded" out loud.

---

### 0:00–0:20 · The problem · *Business value*

**Screen:** deck slide 2 ("Two things slip through"), then the app's empty home screen.

> Every invoice a company pays should match what it ordered and what it received. Accounts-payable
> teams still check that by hand. Two things slip through: overbilling, and invoices that quietly ask
> for payment to a new bank account. The second kind is fraud, and that money rarely comes back.

### 0:20–0:40 · What LedgerPilot is · *Presentation*

**Screen:** the app header. Hover over the model line ("Model: … served on AMD Token Factory").

> LedgerPilot is an accounts-payable agent. It reads the purchase order, the delivery note and the
> invoice, checks them against each other, and tells the clerk: pay, hold, or block. It runs on Evolus,
> and its model is an open model, DeepSeek-V4-Flash, running on AMD GPUs through AMD Token Factory.

### 0:40–1:05 · Case 01, clean · *Application of technology*

**Screen:** click **Clean invoice (case 01)**. Let the progress lines show, then the green stamp.

> Here's a clean invoice. Three Evolus document extractors read the three PDFs. Python checks every
> line, and the agent on AMD reviews the evidence. Ready to pay, high confidence, and it still waits
> for a person's yes in the review queue.

### 1:05–1:35 · Case 07, overbilled · *Business value*

**Screen:** click **Overcharged by $200 (case 07)**. Point at the highlighted price cell, the finding with
its code `PRICE_VARIANCE`, the $200 money at risk, and the drafted email.

> This one bills twenty-two dollars a chair against twenty on the purchase order, for a hundred chairs.
> The checks find exactly two hundred dollars at risk, and show which rule fired. Every number comes
> from code, not the model. An Evolus AI Tool has already drafted the email to the supplier.

### 1:35–2:00 · Case 15, payment diversion · *Originality*

**Screen:** click **Bank account changed (case 15)**. Point at `BANK_MISMATCH`, the masked bank account
and the alert draft. Then open **What ran, where** and show the extractor, agent, AI Tool and workflow rows.

> Now the expensive one. Prices, quantities and totals are all correct, but the bank account doesn't
> match our vendor master. Payment blocked. The finance manager gets an alert, and an Evolus workflow
> routes the case. The agent can make a decision stricter, never looser, so it can't approve fraud.

### 2:00–2:20 · Architecture · *Application of technology*

**Screen:** deck slide 5 (architecture).

> Under the hood: the app drives Evolus through its REST API: extractors, an AI Tool, a workflow and a
> knowledge library holding the vendor master. The agent's model runs on AMD Token Factory, AMD's
> OpenAI-compatible model API. When the agent is unsure, the invoice goes to a person.

### 2:20–2:45 · Results · *Business value*

**Screen:** deck slide 8 (results), or the app's **Results** tab.

> We measured it live on twenty-four cases. [__] false approvals out of seventeen problem invoices.
> [__] of five fraud attempts blocked. [__] percent routed correctly. On AMD Token Factory the agent
> answers in about [__] seconds per invoice.

### 2:45–3:00 · Close · *Presentation*

**Screen:** deck slide 9 (business value), then slide 10.

> That's [__] minutes back on every invoice, and fraud stopped before it's paid. LedgerPilot: Evolus
> agents on AMD. The code, the tests and the evaluation are in our repo. Thank you.

---

**Timing check:** read it aloud once with a stopwatch. If it runs long, cut the architecture scene to
one sentence; never cut the results scene.
