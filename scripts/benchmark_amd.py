"""Measure the agent step on your AMD model endpoint.

Calls the endpoint directly with realistic agent-sized prompts, at several
concurrency levels, and writes docs/benchmark.md + docs/benchmark.json.

AMD Token Factory (the default endpoint) is free and shared: the whole team uses one
key, limited to about 20 requests a minute and 8 at once. The script spots it, keeps
to --rpm (default 10, half the limit, so teammates aren't throttled) and at most 8
requests at once, and reports latency and tokens per invoice instead of a GPU cost:

    python scripts/benchmark_amd.py --label "DeepSeek-V4-Flash"

Your own vLLM droplet has no such limits; there the script measures throughput and
cost per invoice at your GPU price:

    python scripts/benchmark_amd.py --requests 40 --concurrency 1 4 16 --gpu-price 1.99 --label "Qwen2.5-32B"
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openai import OpenAI  # noqa: E402

from ledgerpilot.agent_client import AGENT_INSTRUCTIONS, model_client, model_extra_body  # noqa: E402
from ledgerpilot.config import load_settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# Every sample case with a readable invoice (the corrupt-PDF case has none to send)
TRUTHS = [t for t in (json.loads(p.read_text()) for p in sorted((ROOT / "data/samples").glob("case_*/truth.json")))
          if t["invoice"]]
TF_MAX_CONCURRENCY = 8  # Token Factory: concurrent requests per key


class Pacer:
    """Spaces request starts so the whole run stays under a requests-per-minute budget."""

    def __init__(self, rpm: float | None):
        self.gap = 60.0 / rpm if rpm else 0.0
        self.next_at = time.monotonic()
        self.lock = threading.Lock()

    def wait(self) -> None:
        if not self.gap:
            return
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_at)
            self.next_at = start + self.gap
        time.sleep(max(0.0, start - now))


def case_prompt(i: int) -> str:
    truth = TRUTHS[i % len(TRUTHS)]
    return "CASE:\n" + json.dumps({k: truth[k] for k in ("po", "grn", "invoice")}, indent=2)


def one_call(client: OpenAI, model: str, i: int, pacer: Pacer, extra_body: dict | None) -> dict:
    pacer.wait()
    t = time.perf_counter()
    r = client.chat.completions.create(model=model, max_tokens=300, temperature=0, extra_body=extra_body,
                                       messages=[{"role": "system", "content": AGENT_INSTRUCTIONS},
                                                 {"role": "user", "content": case_prompt(i)}])
    latency = time.perf_counter() - t
    return {"latency": latency, "in": r.usage.prompt_tokens, "out": r.usage.completion_tokens,
            "empty": not (r.choices[0].message.content or "").strip()}


def vllm_table(rows: list[dict]) -> list[str]:
    lines = ["## Your vLLM endpoint on AMD Instinct MI300X", "",
             "| Model | Concurrency | p50 latency (s) | p95 latency (s) | Output tokens/s | Invoices/hour | USD per 1,000 invoices |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    return lines + [f"| {r['label']} | {r['concurrency']} | {r['p50_latency_s']} | {r['p95_latency_s']} | {r['output_tokens_per_s']} "
                    f"| {r['invoices_per_hour']:,} | {r['usd_per_1000_invoices']} |" for r in rows]


def tf_table(rows: list[dict]) -> list[str]:
    lines = ["## AMD Token Factory (free, shared endpoint)", "",
             "Requests were paced to stay under the team's shared rate limit, so throughput reflects the limit, "
             "not the hardware. Latency and tokens per invoice are the useful numbers.", "",
             "| Model | Concurrency | Requests | Paced at (req/min) | p50 latency (s) | p95 latency (s) "
             "| Output tokens/s per request | Input tokens per invoice | Output tokens per invoice | Cost |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    return lines + [f"| {r['label']} | {r['concurrency']} | {r['requests']} | {r['rpm']} | {r['p50_latency_s']} "
                    f"| {r['p95_latency_s']} | {r['per_request_tokens_per_s']} | {r['avg_input_tokens']} "
                    f"| {r['avg_output_tokens']} | free |" for r in rows]


def main() -> None:
    s = load_settings()
    tf = s.token_factory
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=12 if tf else 40)
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 4] if tf else [1, 4, 16])
    ap.add_argument("--rpm", type=float, default=10 if tf else 0,
                    help="max requests per minute (Token Factory default 10; 0 = no pacing)")
    ap.add_argument("--gpu-price", type=float, default=1.99, help="USD per GPU-hour (vLLM droplet only)")
    ap.add_argument("--label", default="", help="e.g. 'DeepSeek-V4-Flash' or 'Qwen2.5-32B'")
    a = ap.parse_args()
    if problem := s.model_problem():
        sys.exit(problem)
    if tf:
        a.concurrency = sorted({min(c, TF_MAX_CONCURRENCY) for c in a.concurrency})
        if a.rpm <= 0 or a.rpm > 20:
            sys.exit("Token Factory allows about 20 requests a minute per account, shared with your team. "
                     "Use --rpm between 1 and 20 (default 10).")
        total = a.requests * len(a.concurrency) + 1
        print(f"AMD Token Factory: {total} requests at {a.rpm:g}/min, about {total / a.rpm:.1f} min. "
              "This uses your team's shared quota.")
    # The SDK retries 429s itself, honouring Retry-After
    client = model_client(s, timeout=300, max_retries=5 if tf else 2)
    model, extra = s.amd_model, model_extra_body(s)
    pacer = Pacer(a.rpm or None)
    one_call(client, model, 0, pacer, extra)  # warm-up

    rows = []
    for c in a.concurrency:
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=c) as pool:
            results = list(pool.map(lambda i: one_call(client, model, i, pacer, extra), range(a.requests)))
        wall = time.perf_counter() - start
        lat = sorted(r["latency"] for r in results)
        row = {"label": a.label, "provider": "token_factory" if tf else "vllm", "concurrency": c,
               "requests": a.requests, "wall_s": round(wall, 2),
               "p50_latency_s": round(statistics.median(lat), 2), "p95_latency_s": round(lat[int(0.95 * (len(lat) - 1))], 2)}
        if tf:
            row.update(rpm=a.rpm,
                       per_request_tokens_per_s=round(statistics.median(r["out"] / r["latency"] for r in results), 1),
                       avg_input_tokens=round(statistics.mean(r["in"] for r in results)),
                       avg_output_tokens=round(statistics.mean(r["out"] for r in results)))
        else:
            per_hour = a.requests / wall * 3600
            row.update(output_tokens_per_s=round(sum(r["out"] for r in results) / wall, 1),
                       invoices_per_hour=round(per_hour), usd_per_1000_invoices=round(a.gpu_price / per_hour * 1000, 4))
        rows.append(row)
        print(row)
        if empty := sum(r["empty"] for r in results):
            print(f"  warning: {empty} empty replies. A thinking model used up max_tokens; "
                  "set AMD_REASONING_EFFORT=low (or none) or pick a model that doesn't think by default.")

    out_json = ROOT / "docs" / "benchmark.json"
    existing = json.loads(out_json.read_text()) if out_json.exists() else []
    existing += rows
    out_json.write_text(json.dumps(existing, indent=2))
    tf_rows = [r for r in existing if r.get("provider") == "token_factory"]
    vllm_rows = [r for r in existing if r.get("provider", "vllm") == "vllm"]
    lines = ["# AMD model benchmark (agent step)", ""]
    if tf_rows:
        lines += tf_table(tf_rows) + [""]
    if vllm_rows:
        lines += [f"Model served by vLLM on 1x AMD Instinct MI300X; GPU price assumed ${a.gpu_price}/hour.", ""]
        lines += vllm_table(vllm_rows) + [""]
    (ROOT / "docs" / "benchmark.md").write_text("\n".join(lines))
    print("wrote docs/benchmark.md")


if __name__ == "__main__":
    main()
