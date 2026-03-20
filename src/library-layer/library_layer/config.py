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

    # ── Infrastructure ARNs / URLs (populated by CDK as Lambda env vars) ──────
    DB_SECRET_ARN: str
    SFN_ARN: str
    APP_CRAWL_QUEUE_URL: str
    REVIEW_CRAWL_QUEUE_URL: str
    STEAM_API_KEY_SECRET_ARN: str
    ASSETS_BUCKET_NAME: str
    STEP_FUNCTIONS_ARN: str

    # ── SNS Domain Topic ARNs ─────────────────────────────────────────────────
    GAME_EVENTS_TOPIC_ARN: str
    CONTENT_EVENTS_TOPIC_ARN: str
    SYSTEM_EVENTS_TOPIC_ARN: str

    # ── Eligibility threshold — overridable via env var or SSM at runtime ──────
    REVIEW_ELIGIBILITY_THRESHOLD: int = 500

    # ── S3 raw response archival (optional) ─────────────────────────────────
    ARCHIVE_BUCKET: str = ""  # empty means archival disabled

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @classmethod
    def for_environment(cls, environment: str) -> Self:
        """Load config from .env.{environment} — used by CDK at synth time."""
        return cls(_env_file=f".env.{environment}")
