"""Steam API metrics callback factory — shared across crawler handlers."""

from collections.abc import Callable

from aws_lambda_powertools.metrics import MetricUnit, single_metric


def make_steam_metrics_callback(environment: str) -> Callable[[str, str, int, float], None]:
    """Return an on_request callback for DirectSteamSource that emits CloudWatch metrics."""

    def _callback(endpoint: str, region: str, status_code: int, latency_ms: float) -> None:
        with single_metric(name="SteamApiRequests", unit=MetricUnit.Count, value=1, namespace="SteamPulse") as m:
            m.add_dimension(name="environment", value=environment)
            m.add_dimension(name="region", value=region)
            m.add_dimension(name="endpoint", value=endpoint)
            m.add_metric(name="SteamApiLatency", unit=MetricUnit.Milliseconds, value=latency_ms)
            if status_code in (429, 503):
                m.add_metric(name="SteamApiRetries", unit=MetricUnit.Count, value=1)
        if status_code >= 400:
            with single_metric(name="SteamApiErrors", unit=MetricUnit.Count, value=1, namespace="SteamPulse") as m:
                m.add_dimension(name="environment", value=environment)
                m.add_dimension(name="region", value=region)
                m.add_dimension(name="endpoint", value=endpoint)
                m.add_dimension(name="status_code", value=str(status_code))

    return _callback
