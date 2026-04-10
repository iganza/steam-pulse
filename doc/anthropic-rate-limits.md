# Anthropic API Rate Limits (as of 2026-04-10)

## Per-model limits

| Model | Requests/min | Input tokens/min | Output tokens/min |
|---|---|---|---|
| Claude Sonnet | 4,000 | 2M (excl. cache reads) | 400K |
| Claude Opus | 4,000 | 2M (excl. cache reads) | 400K |
| Claude Haiku | 4,000 | 4M (excl. cache reads) | 800K |
| Claude Haiku 3 | 4,000 | 400K | 80K |

## Cross-model limits

| Resource | Limit |
|---|---|
| Batch requests | 4,000/min across all models |
| Web search tool uses | 30/sec across all models |
| Files API storage | 500 GB per organization |
