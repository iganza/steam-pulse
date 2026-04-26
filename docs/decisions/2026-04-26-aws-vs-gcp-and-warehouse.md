# AWS vs GCP, and the analytics warehouse question

**Date:** 2026-04-26
**Status:** Decided

## Context

Frustration with "little AWS fees adding up" prompted the question: would migrating to GCP be cheaper and more efficient long term? Secondary question: as we drift toward an analytics service (Steam metadata + reviews), does BigQuery offer a real advantage?

Pre-prod, solo-dev. ~$164/mo actual AWS spend, $500/mo budget. ~100–150k analysis-eligible games at scale; 30–50 GB raw review text expected at 5-year horizon (~100 GB total including metadata + LLM-derived).

Architecture keystone: 6-region hub-and-spoke for **Steam API per-IP rate-limit multiplexing** — not vendor-specific. Same shape required on any cloud.

## Decision 1: stay on AWS

Do not migrate to GCP.

**Why:**

- The 6-region spoke fan-out exists to multiplex Steam's per-IP rate limit. GCP's Cloud Run/Functions in 6 regions has the same cost shape (NAT, regional egress, per-invocation).
- Cloud SQL Postgres at small-instance size is *more* expensive than RDS `t4g.small`: ~$25/mo vs $12/mo.
- "Little fees adding up" is an architecture-sprawl problem, not a vendor problem. GCP has line-item parity on NAT, egress, cross-region transfer, per-invocation compute.
- Anthropic models are available on Vertex AI as well as Bedrock — Bedrock isn't a GCP lock-out.
- Solo-dev migration cost (rewriting 9 CDK stacks, sp.py operator tooling, deploy scripts) burns weeks for ~10–20% compute savings: $15–80/mo. Break-even is measured in years.

**Where the cost actually leaks (the real levers):**

1. **NAT** — confirm whether it's a managed Gateway (~$32/mo fixed + data) or a NAT instance (~$3–5/mo on `t4g.nano`). `data_stack.py:47-51` references a `nat_sg` security group for SSM bastion access, suggesting an instance — verify.
2. **Cross-region data transfer** — spokes uploading to primary-region S3. Pennies per GB but multiplied by 6 spokes.
3. **Bedrock / Anthropic batch** — variable, likely the largest non-fixed cost when analyses run.
4. **CloudWatch** — should now be free-tier post-`cost-trim-round-4`; verify with Cost Explorer at *daily* granularity (monthly `USAGE_TYPE` rollups can mislead).

**When to revisit:**

- A vendor-specific GCP service becomes load-bearing for the product (not currently the case).
- Compute spend crosses ~$1k/mo where 10–20% migration savings becomes material.

## Decision 2: no dedicated warehouse — use Athena over S3

Defer BigQuery / ClickHouse / Snowflake until hot queryable data crosses ~1 TB.

**Why:**

- ~100 GB total at 5-year horizon is *not* BigQuery scale. BQ wins at multi-TB.
- Athena over the existing S3 raw crawl JSON costs ~$1–3/mo at solo-dev query volume, with zero new infra. Postgres matviews continue to serve productized aggregates.
- Warehouse choice is **independent** from compute platform: BigQuery federates to S3, Postgres-to-BQ exports are one command. "Switch to GCP for BigQuery" is a non-sequitur.
- Customer-interface choice drives warehouse need. The async-transactions criterion (from the business model) rules out customer-defined SQL and points to pre-canned PDFs + raw data dumps — neither needs a warehouse.

**Right tool by customer interface:**

| Interface | Tool |
|-----------|------|
| Pre-canned dashboards / PDFs | Postgres + matviews (current) |
| Customer-defined SQL | Snowflake per-tenant (multi-cloud, no lock) |
| Programmatic API over derived metrics | Postgres + Cube.js / Hasura |
| Raw data dumps for download | S3 Parquet + signed URLs |
| Embedded charts in customer tools | Cube.js / Metabase embeds |

**When to revisit:**

- Hot queryable data crosses ~1 TB.
- A Tier 2 feature introduces interactive customer query — evaluate Snowflake before BigQuery (multi-cloud, no platform lock-in).

## Open follow-ups (not committed)

- Verify NAT is an instance, not a managed Gateway.
- Audit which Lambdas actually need VPC egress (spokes don't; can hub Lambdas reach RDS via RDS Proxy + IAM?).
- Pull Cost Explorer last-30-days at daily granularity by service to confirm top line items.
- Delete the dead `staging` branch in `data_stack.py:94-133` and `app.py:31-36` if staging is permanently gone.
- Move S3 raw crawl JSON to Glacier Instant Retrieval if cold (4× cheaper than Standard).
