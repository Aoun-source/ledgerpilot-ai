"""Measure what one AMD MI300X costs per invoice for the agent step.

Calls your vLLM endpoint directly with realistic agent-sized prompts, at several
concurrency levels, and writes docs/benchmark.md + docs/benchmark.json.

    python scripts/benchmark_amd.py --requests 40 --concurrency 1 4 16 --gpu-price 1.99

Run it once with the 7B model and once with the 32B model (change
--served-model-name's backing model on the droplet) and keep both tables.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openai import OpenAI  # noqa: E402

from ledgerpilot.agent_client import AGENT_INSTRUCTIONS  # noqa: E402
from ledgerpilot.config import load_settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# Every sample case with a readable invoice (the corrupt-PDF case has none to send)
TRUTHS = [t for t in (json.loads(p.read_text()) for p in sorted((ROOT / "data/samples").glob("case_*/truth.json")))
          if t["invoice"]]


def case_prompt(i: int) -> str:
    truth = TRUTHS[i % len(TRUTHS)]
    return "CASE:\n" + json.dumps({k: truth[k] for k in ("po", "grn", "invoice")}, indent=2)


def one_call(client: OpenAI, model: str, i: int) -> dict:
    t = time.perf_counter()
    r = client.chat.completions.create(model=model, max_tokens=300, temperature=0,
                                       messages=[{"role": "system", "content": AGENT_INSTRUCTIONS},
                                                 {"role": "user", "content": case_prompt(i)}])
    return {"latency": time.perf_counter() - t, "in": r.usage.prompt_tokens, "out": r.usage.completion_tokens}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=40)
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 16])
    ap.add_argument("--gpu-price", type=float, default=1.99, help="USD per GPU-hour (1x MI300X on AMD Developer Cloud)")
    ap.add_argument("--label", default="", help="e.g. 'Qwen2.5-7B' or 'Qwen2.5-32B'")
    a = ap.parse_args()
    s = load_settings()
    client = OpenAI(base_url=s.vllm_base_url, api_key=s.vllm_api_key or "none", timeout=300)
    model = s.vllm_model
    one_call(client, model, 0)  # warm-up

    rows = []
    for c in a.concurrency:
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=c) as pool:
            results = list(pool.map(lambda i: one_call(client, model, i), range(a.requests)))
        wall = time.perf_counter() - start
        lat = sorted(r["latency"] for r in results)
        per_hour = a.requests / wall * 3600
        rows.append({
            "label": a.label, "concurrency": c, "requests": a.requests, "wall_s": round(wall, 2),
            "p50_latency_s": round(statistics.median(lat), 2), "p95_latency_s": round(lat[int(0.95 * (len(lat) - 1))], 2),
            "output_tokens_per_s": round(sum(r["out"] for r in results) / wall, 1),
            "invoices_per_hour": round(per_hour), "usd_per_1000_invoices": round(a.gpu_price / per_hour * 1000, 4),
        })
        print(rows[-1])

    out_json = ROOT / "docs" / "benchmark.json"
    existing = json.loads(out_json.read_text()) if out_json.exists() else []
    existing += rows
    out_json.write_text(json.dumps(existing, indent=2))
    lines = ["# AMD MI300X benchmark (agent step)", "",
             f"Model served by vLLM on 1x AMD Instinct MI300X; GPU price assumed ${a.gpu_price}/hour.", "",
             "| Model | Concurrency | p50 latency (s) | p95 latency (s) | Output tokens/s | Invoices/hour | USD per 1,000 invoices |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {r['label']} | {r['concurrency']} | {r['p50_latency_s']} | {r['p95_latency_s']} | {r['output_tokens_per_s']} "
              f"| {r['invoices_per_hour']:,} | {r['usd_per_1000_invoices']} |" for r in existing]
    (ROOT / "docs" / "benchmark.md").write_text("\n".join(lines) + "\n")
    print("wrote docs/benchmark.md")


if __name__ == "__main__":
    main()
