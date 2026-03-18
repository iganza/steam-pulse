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

# Cross-region inference profile IDs for Bedrock (us.*).
# Verify against AWS Bedrock console if needed.
_HAIKU_DEFAULT = "us.anthropic.claude-haiku-4-5-20250514-v1:0"
_SONNET_DEFAULT = "us.anthropic.claude-sonnet-4-6-20250514-v1:0"


class SteamPulseConfig(BaseSettings):
    """All runtime configuration for SteamPulse Lambda functions.

    Field names are UPPER_CASE to match environment variable conventions.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file_encoding="utf-8",
    )

    # ── Deployment ────────────────────────────────────────────────────────────
    ENVIRONMENT: Literal["staging", "production"] = "staging"

    # ── LLM models ────────────────────────────────────────────────────────────
    HAIKU_MODEL: str = _HAIKU_DEFAULT
    SONNET_MODEL: str = _SONNET_DEFAULT

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

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @classmethod
    def for_environment(cls, environment: str) -> Self:
        """Load config from .env.{environment} — used by CDK at synth time."""
        return cls(_env_file=f".env.{environment}")
