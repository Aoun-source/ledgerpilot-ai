"""Tonight's go/no-go check. Run after filling in .env:

    python scripts/smoke_test.py

1. Your vLLM endpoint on AMD answers and lists the model.
2. Tool calling works (Evolus agents need it).
3. The Evolus API key works and your agent is listed.
4. One extractor call returns JSON for a sample invoice.
5. The agent answers through Evolus (watch /tmp/vllm.log on the droplet: the request arrives there).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openai import OpenAI  # noqa: E402

from ledgerpilot.agent_client import ClerkAgent, vllm_health  # noqa: E402
from ledgerpilot.config import load_settings  # noqa: E402
from ledgerpilot.evolus_client import EvolusClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
s = load_settings()
ok = True


def step(name, fn):
    global ok
    try:
        detail = fn()
        print(f"PASS  {name}  {detail or ''}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"FAIL  {name}  {type(exc).__name__}: {str(exc)[:300]}")


def check_vllm():
    h = vllm_health(s)
    if not h["ok"]:
        raise RuntimeError(h["detail"])
    return f"models={h['models']} latency={h['latency_ms']}ms"


def check_tools():
    c = OpenAI(base_url=s.vllm_base_url, api_key=s.vllm_api_key or "none", timeout=60)
    tools = [{"type": "function", "function": {"name": "hold_invoice", "description": "Hold an invoice for review",
              "parameters": {"type": "object", "properties": {"invoice_id": {"type": "string"}, "reason": {"type": "string"}},
                             "required": ["invoice_id", "reason"]}}}]
    r = c.chat.completions.create(model=s.vllm_model, tools=tools, tool_choice="auto",
                                  messages=[{"role": "user", "content": "Invoice INV-1001 is $200 over the PO. Hold it."}])
    calls = r.choices[0].message.tool_calls
    if not calls:
        raise RuntimeError("no tool call returned: start vLLM with --enable-auto-tool-choice --tool-call-parser hermes")
    return f"{calls[0].function.name}({calls[0].function.arguments})"


def check_evolus_models():
    c = OpenAI(base_url=s.evolus_chat_base, api_key=s.evolus_api_key or "missing", timeout=30)
    ids = [m.id for m in c.models.list().data]
    target = f"{s.evolus_app_id}:{s.evolus_agent_id}"
    if target not in ids:
        raise RuntimeError(f"{target} not in {ids}: check EVOLUS_APP_ID / EVOLUS_AGENT_ID")
    return f"agent found among {len(ids)}"


def check_extractor():
    blob = (ROOT / "data/samples/case_07/invoice.pdf").read_bytes()
    r = EvolusClient(s).extract(s.extractor_invoice_id, "invoice.pdf", blob)
    return json.dumps(r.data)[:200]


def check_agent():
    v = ClerkAgent(s).review({"invoice": {"invoice_number": "TEST-1"}, "discrepancies": [], "rule_route": "approve_for_payment"})
    return f"route={v.route} parsed={v.parsed} {v.latency_s:.1f}s"


step("AMD vLLM endpoint reachable", check_vllm)
step("Tool calling on vLLM", check_tools)
step("Evolus API key + agent", check_evolus_models)
step("Evolus invoice extractor", check_extractor)
step("Agent answers via Evolus (AMD model)", check_agent)
print("\nALL GOOD" if ok else "\nFix the FAIL lines above, then rerun.")
sys.exit(0 if ok else 1)
