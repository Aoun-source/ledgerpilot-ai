# Accounts-payable fraud guide

A short guide for finance clerks and for the Detective Clerk agent. It explains the losses LedgerPilot looks
for, the warning signs, and the safe way to respond. It is general guidance, not legal advice.

## The three-way match

Before an invoice is paid, three documents should agree:

1. **Purchase order (PO):** what the company ordered, from which supplier, at what agreed price.
2. **Goods-received note (GRN) or delivery note:** what actually arrived.
3. **Supplier invoice:** what the supplier asks to be paid.

If the invoice bills more units than were received, more than were ordered, or a higher unit price than the
PO, the difference is money at risk. Arithmetic (line totals, subtotal, tax, total) must also add up.

## Common invoice fraud and errors

| Scheme | What it looks like | Warning signs |
| --- | --- | --- |
| Bank-account change (payment diversion) | A genuine-looking invoice from a real supplier, but the pay-to account is new | New IBAN or account number, urgency, an email asking to "update our details" |
| Business email compromise | A criminal uses or imitates a supplier's or manager's email | Slightly different sender address, unusual tone, pressure to skip normal checks |
| Fake or look-alike supplier | An invoice from a supplier that is not in the vendor master, or whose name is close to a real one | Unknown supplier ID, misspelt name, new supplier with no PO |
| Duplicate invoice | The same invoice is sent twice, sometimes with a slightly changed number | Same amount and supplier, invoice number with an added letter, dash or space |
| Overbilling | Higher price than agreed, units never delivered, or totals that do not add up | Price above the PO, billed quantity above the delivery note, arithmetic errors |
| Inflated tax or charges | Tax or fees well above normal | Tax rate far above the usual rate for that supplier |

## How to verify a supplier safely

- **Never use contact details from the invoice or the email that asked for the change.** Call the supplier on
  the phone number already stored in the vendor master.
- Ask someone who knows the supplier to confirm, and record who you spoke to, when, and what they said.
- A change of bank details should be approved by a second person before any payment uses it.
- If something feels urgent or secret, slow down. Urgency is a common pressure tactic.

## What LedgerPilot does with each case

- **Ready to pay:** the three documents agree and the supplier and bank account match the vendor master.
  A person still gives the final approval.
- **Needs review:** a billing problem such as a price, quantity, arithmetic, missing-data or currency issue.
  The payment is held and a polite query to the supplier is drafted.
- **Payment blocked:** a fraud signal such as a bank-account mismatch, an unknown supplier or a duplicate.
  Nothing is paid until a manager verifies the supplier by phone.

LedgerPilot never pays or approves anything by itself. Every decision waits for a person in the review queue,
and every step is written to the audit log.
