# Evolus workspace setup (about 30 minutes)

Do this after kickoff, in the **event** workspace created from the event link on
[evolus.ai/en/hackathon](https://evolus.ai/en/hackathon). API details:
[evolus.ai/en/developers](https://evolus.ai/en/developers).

## 1. Connect your AMD model

Workspace → **Your models** → add an OpenAI-compatible model.

**AMD Token Factory** (default). Get the team key first at
[notebooks.amd.com/tokenfactory](https://notebooks.amd.com/tokenfactory): every teammate signs in and
clicks **Redeem API Key**, then the key appears.

| Field | Value |
| --- | --- |
| Base URL | `https://developer.amd.com.cn/radeon/api/v1` |
| Model name | `DeepSeek-V4-Flash` (the same as `AMD_MODEL` in `.env`) |
| API key | your team's Token Factory key (`rc-...`) |

Evolus then calls Token Factory with your team's key, so every agent answer and workflow step counts
toward the limits your team shares (about 20 requests a minute, 8 at once, a daily cap).
DeepSeek-V4-Flash supports tool calling and doesn't think unless asked. If you pick a model that
thinks by default (MiMo, GLM, Qwen3.8-27B), give the agent a generous max-tokens setting or replies can
come back empty.

**Your own vLLM droplet** (if your track requires your own endpoint):

| Field | Value |
| --- | --- |
| Base URL | `http://<DROPLET_IP>:8000/v1` |
| Model name | `ledgerpilot-model` (your `--served-model-name`) |
| API key | the value you passed to vLLM `--api-key` |

vLLM must run with `--enable-auto-tool-choice --tool-call-parser hermes`.

Click **Test connection**.

## 2. Create the agent "LedgerPilot Clerk"

- Model: your AMD model from step 1.
- Instructions: paste `AGENT_INSTRUCTIONS` from `src/ledgerpilot/agent_client.py`.
- Temperature: low (0 to 0.2). Request parameters are ignored; the agent's settings apply.
- Attach the knowledge library from step 4.
- Copy its **agent ID** into `.env` as `EVOLUS_AGENT_ID`.

## 3. Create three document extractors (JSON output)

Define each schema with exactly these field names. LedgerPilot validates them with Pydantic, and
also accepts the camelCase names Evo suggests (`invoiceNumber`). In the extractor choose **Start from
scratch**, then **Advanced settings → Edit the JSON by hand** and paste the structure below: the field
editor has no list type, so `lines` only comes out as a real list from the hand-written JSON.

In the Evolus UI each extractor is its own agent holding one format, and the endpoint path needs both
(`/agents/{agentId}/json/{formatId}/ask-file`). The agent ID is in the extractor's page address; the
format ID appears in the API calls the page makes (`.../json/{formatId}/executions`). Write each one in
`.env` as `agentId/formatId`, for example `EVOLUS_EXTRACTOR_INVOICE_ID=9a4f.../edc2...`. A plain
format ID still works and uses `EVOLUS_EXTRACTOR_AGENT_ID` (or the Clerk's agent).

**Invoice** (`EVOLUS_EXTRACTOR_INVOICE_ID`)

```json
{
  "invoice_number": "string",
  "invoice_date": "YYYY-MM-DD",
  "po_number": "string (the buyer's PO reference)",
  "supplier_id": "string (supplier ID printed on the invoice)",
  "supplier_name": "string",
  "currency": "ISO code, e.g. USD",
  "bank_iban": "string (pay-to account, no spaces)",
  "lines": [{"sku": "string", "description": "string", "qty": "number", "unit_price": "number", "line_total": "number"}],
  "subtotal": "number",
  "tax": "number",
  "total": "number (total due)"
}
```

**Purchase order** (`EVOLUS_EXTRACTOR_PO_ID`)

```json
{
  "po_number": "string", "po_date": "YYYY-MM-DD", "supplier_id": "string", "supplier_name": "string",
  "currency": "ISO code",
  "lines": [{"sku": "string", "description": "string", "qty": "number", "unit_price": "number"}]
}
```

**Goods-received note** (`EVOLUS_EXTRACTOR_GRN_ID`)

```json
{
  "grn_number": "string", "po_number": "string", "received_date": "YYYY-MM-DD", "supplier_id": "string",
  "lines": [{"sku": "string", "description": "string", "qty_received": "number"}]
}
```

In each extractor's instructions add: *"Copy values exactly as printed. Use null when a value is missing
or unreadable. Never guess."*

## 4. Knowledge library "Vendor master and AP policy"

Create the library, copy its ID to `EVOLUS_LIBRARY_ID`, then upload through the API
(this also counts as API usage for judging):

```bash
python scripts/upload_library.py
```

Attach the library to the LedgerPilot Clerk agent.

## 5. Workflow "Exception routing"

A simple first version is enough:

1. Trigger: API call (LedgerPilot sends `input` text plus `parameters`:
   `route`, `invoice_number`, `supplier_id`, `money_at_risk`, `codes`).
2. Condition on `route`:
   - `escalate_fraud` → agent step that writes a one-paragraph incident note → Webhook/notification.
   - `hold_for_review` → agent step that summarises the hold → Webhook/notification.
   - otherwise → end.
3. **Turn the workflow on** (a workflow that is off returns 409).
4. Copy its ID to `EVOLUS_WORKFLOW_ID`.

Declare the five parameters in the workflow so Evolus accepts them.

## 6. AI Tool

Nothing to configure: LedgerPilot calls `POST /api/v1/ai-tools/email/run` to draft supplier
queries and fraud alerts.

## 7. Check

```bash
python scripts/smoke_test.py
```

All five lines should say PASS. On Token Factory it also prints your team's remaining usage.
