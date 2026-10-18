# AMD model benchmark (agent step)

## AMD Token Factory (free, shared endpoint)

Requests were paced to stay under the team's shared rate limit, so throughput reflects the limit, not the hardware. Latency and tokens per invoice are the useful numbers.

| Model | Concurrency | Requests | Paced at (req/min) | p50 latency (s) | p95 latency (s) | Output tokens/s per request | Input tokens per invoice | Output tokens per invoice | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DeepSeek-V4-Flash | 1 | 12 | 10 | 7.76 | 17.38 | 21.3 | 931 | 163 | free |
| DeepSeek-V4-Flash | 4 | 12 | 10 | 8.64 | 15.72 | 19.2 | 931 | 166 | free |
