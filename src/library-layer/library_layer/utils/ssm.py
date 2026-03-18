"""SSM Parameter Store utilities for runtime configuration."""

import logging
import time
from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    from library_layer.config import SteamPulseConfig

logger = logging.getLogger(__name__)

_ssm_cache: dict[str, tuple[int, float]] = {}  # key → (value, expiry)
_SSM_TTL = 300  # 5 minutes


def get_eligibility_threshold(config: "SteamPulseConfig", env: str = "staging") -> int:
    """Read threshold from SSM with 5-min cache. Falls back to config default."""
    cache_key = "review_eligibility_threshold"
    now = time.time()
    if cache_key in _ssm_cache and _ssm_cache[cache_key][1] > now:
        return _ssm_cache[cache_key][0]
    try:
        ssm = boto3.client("ssm")
        param = ssm.get_parameter(Name=f"/steampulse/{env}/config/review-eligibility-threshold")
        value = int(param["Parameter"]["Value"])
        _ssm_cache[cache_key] = (value, now + _SSM_TTL)
        return value
    except Exception:
        logger.debug("SSM threshold lookup failed, using config default")
        return config.REVIEW_ELIGIBILITY_THRESHOLD
