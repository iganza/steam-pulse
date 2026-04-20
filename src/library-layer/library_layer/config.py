"""SteamPulse runtime configuration backed by pydantic-settings.

Two usage patterns:

  CDK (synth time) — loads from .env.{environment} file:
      config = SteamPulseConfig.for_environment("staging")
      config.ENVIRONMENT          # → "staging"
      config.is_production        # → False

  Lambda (runtime) — reads from os.environ (set by CDK at deploy):
      config = SteamPulseConfig()

The naming convention for env files is encapsulated here.
Secrets (DB password, Steam API key) never appear in env files —
they live in Secrets Manager and are fetched at runtime.
"""

from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SteamPulseConfig(BaseSettings):
    """All runtime configuration for SteamPulse Lambda functions.

    Field names are UPPER_CASE to match environment variable conventions.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    # ── Deployment ────────────────────────────────────────────────────────────
    ENVIRONMENT: Literal["staging", "production"] = "staging"

    # ── LLM backend selection ────────────────────────────────────────────────
    # "bedrock" (default) uses AnthropicBedrock via instructor.
    # "anthropic" uses the direct Anthropic Messages API (higher rate limits,
    # 50 % batch discount). ANTHROPIC_API_KEY is required when "anthropic".
    LLM_BACKEND: Literal["bedrock", "anthropic"] = "bedrock"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_API_KEY_SECRET_NAME: str = ""

    @model_validator(mode="after")
    def _validate_anthropic_config(self) -> Self:
        if self.LLM_BACKEND == "anthropic":
            if not self.ANTHROPIC_API_KEY and not self.ANTHROPIC_API_KEY_SECRET_NAME:
                raise ValueError(
                    "LLM_BACKEND=anthropic requires ANTHROPIC_API_KEY or "
                    "ANTHROPIC_API_KEY_SECRET_NAME to be set."
                )
        return self

    # ── LLM model routing (required — set LLM_MODEL__<task> in .env files) ──
    # Known tasks: chunking, merging, summarizer
    # Add new tasks by adding LLM_MODEL__<newtask>=<model_id> to env files.
    LLM_MODEL: dict[str, str]

    def model_for(self, task: str) -> str:
        """Return the configured model ID for a named LLM task.

        Raises ValueError with a clear message if the task is not configured,
        so misconfiguration fails loudly rather than silently using a wrong model.

        Usage:
            config.model_for("chunking")    # Pass 1 — review chunk extraction
            config.model_for("summarizer")  # Pass 2 — final report synthesis
        """
        if task not in self.LLM_MODEL:
            configured = list(self.LLM_MODEL.keys())
            raise ValueError(
                f"No model configured for task '{task}'. "
                f"Add LLM_MODEL__{task.upper()}=<model_id> to your .env file. "
                f"Currently configured tasks: {configured}"
            )
        return self.LLM_MODEL[task]

    # ── Secrets Manager names (Lambda calls get_secret_value(SecretId=name)) ──
    DB_SECRET_NAME: str
    STEAM_API_KEY_SECRET_NAME: str
    RESEND_API_KEY_SECRET_NAME: str

    # ── SSM parameter names (resolved at Lambda cold start via get_parameter()) ─
    SFN_PARAM_NAME: str
    STEP_FUNCTIONS_PARAM_NAME: str
    APP_CRAWL_QUEUE_PARAM_NAME: str
    REVIEW_CRAWL_QUEUE_PARAM_NAME: str
    ASSETS_BUCKET_PARAM_NAME: str
    EMAIL_QUEUE_PARAM_NAME: str

    # ── SNS topic SSM parameter names ──────────────────────────────────────────
    GAME_EVENTS_TOPIC_PARAM_NAME: str
    CONTENT_EVENTS_TOPIC_PARAM_NAME: str
    SYSTEM_EVENTS_TOPIC_PARAM_NAME: str

    # ── Spoke regions (comma-separated, e.g. "us-west-2,us-east-1") ───────────
    SPOKE_REGIONS: str = ""
    SPOKE_CRAWL_QUEUE_URLS: str = ""

    @property
    def spoke_region_list(self) -> list[str]:
        """Return list of spoke regions, filtering out empty strings."""
        return [r.strip() for r in self.SPOKE_REGIONS.split(",") if r.strip()]

    @property
    def spoke_crawl_queue_url_list(self) -> list[str]:
        """Return list of per-spoke SQS crawl queue URLs, filtering out empty strings."""
        return [u.strip() for u in self.SPOKE_CRAWL_QUEUE_URLS.split(",") if u.strip()]

    # ── Review crawl limits — overridable via env var ───────────────────────────
    REVIEW_ELIGIBILITY_THRESHOLD: int = 50
    REVIEW_LIMIT: int = 10_000  # Default cap for automated (SQS-driven) crawls.
    # Operators can override per-invocation via direct invoke.

    # ── Tiered refresh scheduling ─────────────────────────────────────────────
    # Tier intervals (days). Each game's "due" time is computed as
    #   last_crawled_at + tier_interval
    #   + (abs(hashtext(appid::text)::bigint) % tier_interval_seconds)
    # so work is smeared evenly across the window rather than firing on a boundary.
    # Metadata covers S/A/B/C; reviews cover S/A/B only (tier C excluded).
    REFRESH_META_TIER_S_DAYS: int = 2
    REFRESH_META_TIER_A_DAYS: int = 7
    REFRESH_META_TIER_B_DAYS: int = 21
    REFRESH_META_TIER_C_DAYS: int = 90
    REFRESH_REVIEWS_TIER_S_DAYS: int = 1
    REFRESH_REVIEWS_TIER_A_DAYS: int = 3
    REFRESH_REVIEWS_TIER_B_DAYS: int = 14

    # Tier membership review-count thresholds (first match wins).
    #   S: review_count >= REFRESH_TIER_S_REVIEW_COUNT
    #   A: coming_soon OR EA genre OR review_count >= REFRESH_TIER_A_REVIEW_COUNT
    #   B: review_count >= REFRESH_TIER_B_REVIEW_COUNT
    #   C: everything else
    # The B threshold MUST equal REVIEW_ELIGIBILITY_THRESHOLD — a game is in
    # tier B precisely when it becomes analysis-eligible, so the two thresholds
    # are logically one knob. The validator below enforces this; override
    # BOTH via env if you want to shift the eligibility bar.
    REFRESH_TIER_S_REVIEW_COUNT: int = 10_000
    REFRESH_TIER_A_REVIEW_COUNT: int = 1_000
    REFRESH_TIER_B_REVIEW_COUNT: int = 50

    # Hourly dispatcher batch sizes. Sized against measured tier populations
    # (meta demand ~486/hr, review demand ~402/hr) with ~20–25% headroom.
    # Comfortably under Steam's ~57k/day per-IP appdetails ceiling.
    REFRESH_META_BATCH_LIMIT: int = 600
    REFRESH_REVIEWS_BATCH_LIMIT: int = 500

    @model_validator(mode="after")
    def _validate_refresh_tier_config(self) -> Self:
        """Guard against env overrides that would break the dispatcher SQL.

        Tier day intervals must be >= 1 — zero/negative makes the SMEAR term
        `hashtext(appid) % (days*86400)` divide-by-zero at runtime, taking the
        hourly dispatcher down. Thresholds and batch limits must be positive.
        """
        day_fields = (
            "REFRESH_META_TIER_S_DAYS",
            "REFRESH_META_TIER_A_DAYS",
            "REFRESH_META_TIER_B_DAYS",
            "REFRESH_META_TIER_C_DAYS",
            "REFRESH_REVIEWS_TIER_S_DAYS",
            "REFRESH_REVIEWS_TIER_A_DAYS",
            "REFRESH_REVIEWS_TIER_B_DAYS",
        )
        positive_fields = (
            "REFRESH_TIER_S_REVIEW_COUNT",
            "REFRESH_TIER_A_REVIEW_COUNT",
            "REFRESH_TIER_B_REVIEW_COUNT",
            "REFRESH_META_BATCH_LIMIT",
            "REFRESH_REVIEWS_BATCH_LIMIT",
        )
        for name in day_fields:
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1 (divide-by-zero risk in smear SQL)")
        for name in positive_fields:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.REFRESH_TIER_B_REVIEW_COUNT != self.REVIEW_ELIGIBILITY_THRESHOLD:
            raise ValueError(
                "REFRESH_TIER_B_REVIEW_COUNT "
                f"({self.REFRESH_TIER_B_REVIEW_COUNT}) must equal "
                f"REVIEW_ELIGIBILITY_THRESHOLD ({self.REVIEW_ELIGIBILITY_THRESHOLD}) — "
                "tier B is defined as the analysis-eligibility threshold; "
                "override both together to shift the bar."
            )
        return self

    # ── Three-phase analyzer tuning knobs ───────────────────────────────────
    # These are the SINGLE place default values live for the realtime and
    # batch analysis pipelines. Every downstream function requires these to
    # be passed explicitly — no function signature carries its own default.
    # Override any of them in .env.{environment} via `ANALYSIS_<NAME>=...`.
    #
    # ANALYSIS_MAX_REVIEWS: how many reviews per game feed Phase 1. Larger
    #   values cost more tokens and merge-phase levels; smaller values may
    #   miss long-tail signal.
    ANALYSIS_MAX_REVIEWS: int = 2000
    # ANALYSIS_CHUNK_SIZE: reviews per Phase 1 chunk. Bounded by the
    #   chunking model's input+output budget at CHUNK_MAX_TOKENS below.
    ANALYSIS_CHUNK_SIZE: int = 50
    # ANALYSIS_MAX_CHUNKS_PER_MERGE_CALL: per-call LLM context-budget limit
    #   for the merge phase. Larger chunk counts are handled by hierarchical
    #   recursion; this is NOT a review-count limit.
    ANALYSIS_MAX_CHUNKS_PER_MERGE_CALL: int = 40
    # ANALYSIS_*_MAX_TOKENS: Bedrock max_tokens budget per phase call. Must
    #   be large enough for the response model's full JSON under the worst
    #   reasonable topic count.
    ANALYSIS_CHUNK_MAX_TOKENS: int = 1024
    ANALYSIS_MERGE_MAX_TOKENS: int = 4096
    ANALYSIS_SYNTHESIS_MAX_TOKENS: int = 5000
    # ANALYSIS_CONVERSE_MAX_WORKERS: chunk-phase thread pool fan-out for
    #   ConverseBackend. boto3 + instructor clients are thread-safe per
    #   Anthropic SDK docs.
    ANALYSIS_CONVERSE_MAX_WORKERS: int = 8
    ANALYSIS_CONVERSE_MAX_RETRIES: int = 2
    # ANALYSIS_CHUNK_SHUFFLE_SEED: deterministic in-chunk shuffle seed so
    #   tests/replays are stable.
    ANALYSIS_CHUNK_SHUFFLE_SEED: int = 42
    # ANALYSIS_*_TEMPERATURE: per-phase temperature. Lower = more
    #   deterministic, better schema adherence (important for Haiku chunking).
    #   Anthropic default is 1.0. 0.0 = greedy. Empty string = use API default.
    ANALYSIS_CHUNK_TEMPERATURE: str = "0.2"
    ANALYSIS_MERGE_TEMPERATURE: str = "0.2"
    ANALYSIS_SYNTHESIS_TEMPERATURE: str = ""

    # ── Batch dispatch tuning knobs ───────────────────────────────────────
    BATCH_DISPATCH_SIZE: int = 100

    # ── Phase-4 cross-genre synthesizer tuning knobs ─────────────────────
    # Single LLM call per genre per refresh, consuming per-game GameReports.
    # MIN_REPORTS_PER_GENRE: refuse to synthesize below this (noise floor).
    # MAX_REPORTS_PER_GENRE: sample by review_count DESC if the eligible
    #   set is larger (context-budget cap).
    # GENRE_SYNTHESIS_MAX_TOKENS: Sonnet output budget for the tool_use
    #   response. Must fit the worst-case GenreSynthesis payload.
    # GENRE_SYNTHESIS_PROMPT_VERSION: change to force a re-synthesis via
    #   input_hash cache miss. The cache key is sha256(prompt_version ||
    #   required Phase-3 pipeline_version || sorted_appids) — so either
    #   a prompt bump here OR a Phase-3 PIPELINE_VERSION bump (the
    #   analyzer constant) also forces Phase-4 to re-synthesize.
    # GENRE_SYNTHESIS_MIN_GAME_REVIEW_COUNT: only include games with at
    #   least this many Steam reviews (low-signal games would drag the
    #   synthesis toward noise).
    # GENRE_SYNTHESIS_MAX_AGE_DAYS: weekly refresh threshold used by
    #   find_stale() in the EventBridge scan.
    # GENRE_SYNTHESIS_QUEUE_PARAM_NAME: SSM path for the synthesis SQS
    #   queue URL. Lambda resolves at cold start.
    MIN_REPORTS_PER_GENRE: int = 30
    MAX_REPORTS_PER_GENRE: int = 200
    GENRE_SYNTHESIS_MAX_TOKENS: int = 8000
    GENRE_SYNTHESIS_PROMPT_VERSION: str = "v1"
    GENRE_SYNTHESIS_MIN_GAME_REVIEW_COUNT: int = 200
    GENRE_SYNTHESIS_MAX_AGE_DAYS: int = 7
    GENRE_SYNTHESIS_QUEUE_PARAM_NAME: str = ""

    def to_lambda_env(self, **overrides: str) -> dict[str, str]:
        """Build a Lambda environment dict from this config.

        Serialises all config fields as flat key=string pairs.
        Nested dicts (LLM_MODEL) are flattened with __ delimiter.
        Overrides are applied last (for POWERTOOLS_* and similar).
        """
        env: dict[str, str] = {}
        for k, v in self.model_dump().items():
            if isinstance(v, dict):
                for nk, nv in v.items():
                    env[f"{k}__{nk.upper()}"] = str(nv)
            elif isinstance(v, bool):
                env[k] = str(v).lower()
            else:
                env[k] = str(v)
        env.update(overrides)
        return env

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def library_layer_ssm_path(self) -> str:
        return f"/steampulse/{self.ENVIRONMENT}/compute/library-layer-arn"

    @classmethod
    def for_environment(cls, environment: str) -> Self:
        """Load config from .env.{environment} — used by CDK at synth time."""
        return cls(_env_file=f".env.{environment}")
