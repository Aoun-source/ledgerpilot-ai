# Evaluation - DeepSeek-V4-Flash

24 synthetic cases (data/samples), full pipeline: Evolus extractors -> Python rules -> agent on AMD Token Factory.
Model reported by the AMD endpoint: DeepSeek-V4-Flash.

| Metric | Result | Definition |
| --- | --- | --- |
| False approvals | 0 of 17 | problem or unreadable cases marked ready to pay |
| Routing accuracy | 96% | final route = expected route |
| Exception recall | 100% | problem cases not approved |
| Fraud recall | 100% | fraud cases escalated as fraud |
| False alarms | 14% | clean cases not approved |
| Field extraction accuracy | 99% | extracted fields equal to ground truth |
| Agent agreement | 96% | agent's own route = expected route |
| Median end-to-end latency | 45.215 s | upload to decision |
| p95 end-to-end latency | 64.4 s | upload to decision |
| Median agent latency | 20.29 s | AMD Token Factory model via Evolus |

## Accuracy by case type

| Case type | Cases | Routed correctly |
| --- | --- | --- |
| Billing error (hold): CURRENCY_MISMATCH | 1 | 1 of 1 |
| Billing error (hold): ITEM_NOT_ON_PO | 1 | 1 of 1 |
| Billing error (hold): LINE_ARITHMETIC | 1 | 1 of 1 |
| Billing error (hold): NEGATIVE_VALUE | 1 | 1 of 1 |
| Billing error (hold): PO_ALREADY_BILLED | 1 | 1 of 1 |
| Billing error (hold): PRICE_VARIANCE | 2 | 2 of 2 |
| Billing error (hold): QTY_NOT_RECEIVED | 1 | 1 of 1 |
| Billing error (hold): QTY_OVER_PO | 1 | 1 of 1 |
| Billing error (hold): TAX_OUT_OF_RANGE | 1 | 1 of 1 |
| Billing error (hold): TOTAL_ARITHMETIC | 1 | 1 of 1 |
| Clean invoice | 7 | 6 of 7 |
| Fraud signal (block): BANK_MISMATCH | 1 | 1 of 1 |
| Fraud signal (block): DUPLICATE_INVOICE | 1 | 1 of 1 |
| Fraud signal (block): LOOKALIKE_INVOICE_NUMBER | 1 | 1 of 1 |
| Fraud signal (block): POSSIBLE_DUPLICATE | 1 | 1 of 1 |
| Fraud signal (block): UNKNOWN_VENDOR | 1 | 1 of 1 |
| Unreadable document | 1 | 1 of 1 |

## Every case

| Case | Scenario | Expected | Got | Codes found |
| --- | --- | --- | --- | --- |
| case_01 | Clean three-way match | approve_for_payment | approve_for_payment |  |
| case_02 | Clean three-way match | approve_for_payment | approve_for_payment |  |
| case_03 | Clean three-way match, EUR with 22% VAT | approve_for_payment | hold_for_review (miss) | MISSING_FIELD |
| case_04 | Clean three-way match | approve_for_payment | approve_for_payment |  |
| case_05 | Clean three-way match, EUR with 19% VAT | approve_for_payment | approve_for_payment |  |
| case_06 | Clean three-way match | approve_for_payment | approve_for_payment |  |
| case_07 | Unit price $22 billed vs $20 on PO for 100 chairs ($200 overcharge) | hold_for_review | hold_for_review | PRICE_VARIANCE |
| case_08 | Small price increase on monitors | hold_for_review | hold_for_review | PRICE_VARIANCE |
| case_09 | Billed 100 towel sets, only 90 received | hold_for_review | hold_for_review | QTY_NOT_RECEIVED |
| case_10 | Billed 12 packs, PO ordered 10 (12 delivered) | hold_for_review | hold_for_review | MISSING_FIELD |
| case_11 | Line total wrong: 20 x 18.50 printed as 390.00 | hold_for_review | hold_for_review | LINE_ARITHMETIC |
| case_12 | Total is 100 more than subtotal + VAT | hold_for_review | hold_for_review | TOTAL_ARITHMETIC |
| case_13 | Extra warranty line that is not on the PO | hold_for_review | hold_for_review | ITEM_NOT_ON_PO |
| case_14 | Invoice in USD, PO in EUR | hold_for_review | hold_for_review | CURRENCY_MISMATCH, MISSING_FIELD |
| case_15 | Perfect invoice, but bank account changed (payment-diversion fraud) | escalate_fraud | escalate_fraud | BANK_MISMATCH, MISSING_FIELD |
| case_16 | Invoice number already paid last month | escalate_fraud | escalate_fraud | DUPLICATE_INVOICE |
| case_17 | Same amount as an invoice paid 1 week ago, new number | escalate_fraud | escalate_fraud | POSSIBLE_DUPLICATE |
| case_18 | Look-alike supplier not in vendor master | escalate_fraud | escalate_fraud | UNKNOWN_VENDOR |
| case_19 | Clean three-way match | approve_for_payment | approve_for_payment |  |
| case_20 | Invoice PDF is corrupt / unreadable | processing_error | processing_error |  |
| case_21 | Paid invoice AC-7710 sent again as AC7710 (dash removed) | escalate_fraud | escalate_fraud | LOOKALIKE_INVOICE_NUMBER |
| case_22 | Tax padded to 60% of the subtotal; the sums still add up | hold_for_review | hold_for_review | TAX_OUT_OF_RANGE |
| case_23 | Credit note for 2 returned rolls sent in as an invoice | hold_for_review | hold_for_review | NEGATIVE_VALUE |
| case_24 | PO for 10 docks was fully billed last month; this invoice bills 4 more | hold_for_review | hold_for_review | PO_ALREADY_BILLED |
