#!/usr/bin/env python3
"""Estimate LLM cost for analyzed games.

Reads the persisted token counts from `chunk_summaries` (Phase 1) and
`merged_summaries` (Phase 2), multiplies by the per-model pricing table,
and prints a breakdown per appid (or across the whole local DB).

Supports both Bedrock and Anthropic direct API pricing. The pricing
table includes Bedrock model IDs (with `anthropic.` or `us.anthropic.`
prefixes) and Anthropic direct model IDs (plain `claude-*`). Anthropic
Message Batches API gets 50% off vs realtime — use `--batch` flag to
apply batch pricing.

Token counts were collected by `ConverseBackend._execute_one` via
`completion.usage` from the Anthropic/instructor client. `input_tokens`
in the tables is the SUM of new input tokens + cache-write tokens +
cache-read tokens — the cost estimator treats it as full-rate input,
which OVERESTIMATES slightly on cache-heavy runs (cache reads bill at
~10% of full rate). Good enough for "is this $5 or $50 per game"
precision; for finer accuracy add separate cache columns.

Phase 3 (synthesis) is NOT persisted in any token column today (the
`reports` table has no input_tokens column), so its cost is not
included. It's a single call and typically 10-20% of the chunk-phase
cost for a 2000-review game.

Usage:
    # All games in the local DB
    poetry run python scripts/dev/cost_estimate.py

    # One specific appid
    poetry run python scripts/dev/cost_estimate.py --appid 2358720

    # Anthropic batch pricing (50% off)
    poetry run python scripts/dev/cost_estimate.py --batch

    # JSON output for scripting
    poetry run python scripts/dev/cost_estimate.py --appid 2358720 --json

Pricing source:
    https://aws.amazon.com/bedrock/pricing/
    https://docs.anthropic.com/en/docs/about-claude/models/all-models#model-pricing

    Anthropic batch pricing is 50% of realtime for both input and output.

    Update `_PRICING` below when pricing changes or new models are
    added. The inference-profile IDs (us.anthropic.claude-*) resolve to
    their base model for pricing — we normalize the prefix below.
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")
sys.path.insert(0, str(_REPO_ROOT / "src" / "library-layer"))
sys.path.insert(0, str(_REPO_ROOT / "src" / "lambda-functions"))

from library_layer.utils.db import get_conn  # noqa: E402

# ---------------------------------------------------------------------------
# Pricing table — USD per 1,000,000 tokens.
#
# Update from https://aws.amazon.com/bedrock/pricing/ as Anthropic/AWS
# changes rates or we start using new model IDs. Keys are the base
# Anthropic model string — inference profile prefixes like `us.` are
# stripped before lookup.
#
# Cache-read discount is not applied here (see module docstring) —
# chunk/merge `input_tokens` includes cache reads at the full rate.
# ---------------------------------------------------------------------------

_PRICING: dict[str, dict[str, float]] = {
    # ── Bedrock realtime pricing (Converse API) ────────────────────────
    "anthropic.claude-sonnet-4-6": {
        "input_per_million": 3.00,
        "output_per_million": 15.00,
    },
    "anthropic.claude-haiku-4-5-20251001-v1:0": {
        "input_per_million": 0.80,
        "output_per_million": 4.00,
    },
    "anthropic.claude-haiku-4-5": {
        "input_per_million": 0.80,
        "output_per_million": 4.00,
    },
    # ── Anthropic direct API realtime pricing ──────────────────────────
    # Batch pricing is 50% of these rates — applied via --batch flag.
    "claude-sonnet-4-6": {
        "input_per_million": 3.00,
        "output_per_million": 15.00,
    },
    "claude-haiku-4-5": {
        "input_per_million": 0.80,
        "output_per_million": 4.00,
    },
}

_BATCH_DISCOUNT = 0.50  # Anthropic Message Batches API: 50% off


def _normalize_model_id(model_id: str) -> str:
    """Strip Bedrock inference-profile region prefix (`us.`, `eu.`, ...)."""
    if not model_id:
        return model_id
    head, sep, tail = model_id.partition(".")
    if sep and head.isalpha() and len(head) == 2:
        return tail
    return model_id


def _price(model_id: str) -> dict[str, float] | None:
    normalized = _normalize_model_id(model_id)
    return _PRICING.get(normalized)


def _cost(
    input_tokens: int,
    output_tokens: int,
    rates: dict[str, float],
    *,
    batch: bool,
) -> float:
    discount = _BATCH_DISCOUNT if batch else 1.0
    return (
        input_tokens * rates["input_per_million"] * discount / 1_000_000
        + output_tokens * rates["output_per_million"] * discount / 1_000_000
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--appid", type=int, default=None, help="Limit to a single appid")
    p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p.add_argument(
        "--batch",
        action="store_true",
        help="Apply Anthropic batch pricing (50%% off realtime rates)",
    )
    return p.parse_args()


def _query_phase_totals(
    table: str,
    appid: int | None,
) -> list[dict]:
    where = "WHERE input_tokens IS NOT NULL"
    params: tuple = ()
    if appid is not None:
        where += " AND appid = %s"
        params = (appid,)
    sql = f"""
        SELECT
            appid,
            model_id,
            COUNT(*) AS rows,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(latency_ms), 0) AS latency_ms
        FROM {table}
        {where}
        GROUP BY appid, model_id
        ORDER BY appid, model_id
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    out: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(
                {
                    "appid": row["appid"],
                    "model_id": row["model_id"],
                    "rows": int(row["rows"]),
                    "input_tokens": int(row["input_tokens"]),
                    "output_tokens": int(row["output_tokens"]),
                    "latency_ms": int(row["latency_ms"]),
                }
            )
        else:
            out.append(
                {
                    "appid": row[0],
                    "model_id": row[1],
                    "rows": int(row[2]),
                    "input_tokens": int(row[3]),
                    "output_tokens": int(row[4]),
                    "latency_ms": int(row[5]),
                }
            )
    return out


def _phase_cost_rows(phase: str, totals: list[dict], *, batch: bool) -> list[dict]:
    rows: list[dict] = []
    for t in totals:
        rates = _price(t["model_id"])
        row = {
            "appid": t["appid"],
            "phase": phase,
            "model_id": t["model_id"],
            "rows": t["rows"],
            "input_tokens": t["input_tokens"],
            "output_tokens": t["output_tokens"],
            "latency_ms_total": t["latency_ms"],
        }
        if rates is None:
            row["cost_usd"] = None
            row["note"] = "unknown model pricing — add to _PRICING"
        else:
            row["cost_usd"] = round(
                _cost(t["input_tokens"], t["output_tokens"], rates, batch=batch), 4
            )
            row["note"] = "(batch 50% off)" if batch else ""
        rows.append(row)
    return rows


def _print_human(rows: list[dict]) -> None:
    if not rows:
        print("No persisted token data found.")
        print(
            "Either the analyzer hasn't run on any game yet, or rows pre-date "
            "the token capture change — re-run the phase to populate."
        )
        return

    # Group by appid
    by_appid: dict[int, list[dict]] = {}
    for r in rows:
        by_appid.setdefault(r["appid"], []).append(r)

    grand_total = 0.0
    grand_unknown = 0
    for appid in sorted(by_appid):
        print(f"\n▶ appid={appid}")
        print(
            f"  {'phase':10} {'model':45} {'rows':>5} "
            f"{'in_tok':>10} {'out_tok':>10} {'latency':>10} {'cost_usd':>10}"
        )
        print("  " + "-" * 102)
        appid_total = 0.0
        for r in by_appid[appid]:
            cost_str = f"${r['cost_usd']:.4f}" if r["cost_usd"] is not None else "?"
            print(
                f"  {r['phase']:10} {r['model_id'][:45]:45} {r['rows']:5d} "
                f"{r['input_tokens']:10,d} {r['output_tokens']:10,d} "
                f"{r['latency_ms_total']:9,d}ms {cost_str:>10}"
            )
            if r["cost_usd"] is not None:
                appid_total += r["cost_usd"]
            else:
                grand_unknown += 1
            if r["note"]:
                print(f"           ^^ {r['note']}")
        print(f"  {'TOTAL':<95} ${appid_total:.4f}")
        grand_total += appid_total

    print()
    pricing_mode = "batch (50% off)" if any(r.get("note", "").startswith("(batch") for r in rows) else "realtime"
    print(f"Grand total (chunks + merges, {pricing_mode}): ${grand_total:.4f}")
    if grand_unknown > 0:
        print(f"  ({grand_unknown} row(s) had unknown model pricing — see notes)")
    print()
    print(
        "NOTE: Phase 3 (synthesis) is NOT included — no token columns on the "
        "reports table. Typically 10-20% of the chunk-phase cost for a 2000-review game."
    )
    if pricing_mode == "realtime":
        print("TIP:  Use --batch to see Anthropic batch pricing (50% off).")


def main() -> None:
    args = _parse_args()
    chunk_totals = _query_phase_totals("chunk_summaries", args.appid)
    merge_totals = _query_phase_totals("merged_summaries", args.appid)
    rows = _phase_cost_rows("chunk", chunk_totals, batch=args.batch) + _phase_cost_rows(
        "merge", merge_totals, batch=args.batch
    )

    if args.json:
        print(json.dumps({"rows": rows}, indent=2, default=str))
        return
    _print_human(rows)


if __name__ == "__main__":
    main()
