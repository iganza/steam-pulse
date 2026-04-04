"""Steam API metrics callback factory — shared across crawler handlers."""

from collections.abc import Callable

from aws_lambda_powertools.metrics import Metrics, MetricUnit


def make_steam_metrics_callback(
    environment: str,
    metrics: Metrics | None = None,
) -> Callable[[str, str, int, float], None]:
    """Return an on_request callback for DirectSteamSource.

    Accumulates Steam API metrics onto the provided Metrics instance so they
    are flushed once per Lambda invocation (via @log_metrics) rather than
    emitting one EMF blob per Steam API call.

    Args:
        environment: used only when metrics is None (legacy/test path).
        metrics: the handler's Metrics instance. When provided, add_metric()
            is called directly and the flush is handled by @log_metrics.
    """
    if metrics is not None:

        def _callback(endpoint: str, region: str, status_code: int, latency_ms: float) -> None:
            metrics.add_metric(name="SteamApiRequests", unit=MetricUnit.Count, value=1)
            metrics.add_metric(
                name="SteamApiLatency", unit=MetricUnit.Milliseconds, value=latency_ms
            )
            if status_code in (429, 503):
                metrics.add_metric(name="SteamApiRetries", unit=MetricUnit.Count, value=1)
            if status_code >= 400:
                metrics.add_metric(name="SteamApiErrors", unit=MetricUnit.Count, value=1)

        return _callback

    # Fallback: no Metrics instance (e.g. local dev, tests without moto).
    # Silently drop metrics rather than blowing up.
    def _noop(endpoint: str, region: str, status_code: int, latency_ms: float) -> None:
        pass

    return _noop
