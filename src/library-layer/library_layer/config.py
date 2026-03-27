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

    # ── LLM model routing (required — set LLM_MODEL__<task> in .env files) ──
    # Known tasks: chunking, summarizer
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

    # ── Feature flags ─────────────────────────────────────────────────────────
    PRO_ENABLED: bool = False

    # ── Secrets Manager names (Lambda calls get_secret_value(SecretId=name)) ──
    DB_SECRET_NAME: str
    STEAM_API_KEY_SECRET_NAME: str

    # ── SSM parameter names (resolved at Lambda cold start via get_parameter()) ─
    SFN_PARAM_NAME: str
    STEP_FUNCTIONS_PARAM_NAME: str
    APP_CRAWL_QUEUE_PARAM_NAME: str
    REVIEW_CRAWL_QUEUE_PARAM_NAME: str
    ASSETS_BUCKET_PARAM_NAME: str

    # ── SNS topic SSM parameter names ──────────────────────────────────────────
    GAME_EVENTS_TOPIC_PARAM_NAME: str
    CONTENT_EVENTS_TOPIC_PARAM_NAME: str
    SYSTEM_EVENTS_TOPIC_PARAM_NAME: str

    # ── Spoke regions (comma-separated, e.g. "us-west-2,us-east-1") ───────────
    SPOKE_REGIONS: str = ""

    @property
    def spoke_region_list(self) -> list[str]:
        """Return list of spoke regions, filtering out empty strings."""
        return [r.strip() for r in self.SPOKE_REGIONS.split(",") if r.strip()]

    # ── Review crawl limits — overridable via env var ───────────────────────────
    REVIEW_ELIGIBILITY_THRESHOLD: int = 50
    REVIEW_LIMIT: int = 10_000  # Default cap for automated (SQS-driven) crawls.
                                 # Operators can override per-invocation via direct invoke.

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
