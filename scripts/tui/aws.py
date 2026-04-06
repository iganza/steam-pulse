"""AWS client wrappers for the TUI — SQS, SNS, SSM, SFN, CloudWatch Logs."""


class AwsUnavailableError(Exception):
    """Raised when AWS operations are attempted without --env."""


class AwsClients:
    """Lazy-init boto3 clients with SSM parameter caching."""

    QUEUE_PARAMS = {
        "app-crawl-queue": "/steampulse/{env}/messaging/app-crawl-queue-url",
        "review-crawl-queue": "/steampulse/{env}/messaging/review-crawl-queue-url",
        "spoke-results-queue": "/steampulse/{env}/messaging/spoke-results-queue-url",
        "email-queue": "/steampulse/{env}/messaging/email-queue-url",
    }

    DLQ_PARAMS = {
        "app-crawl-dlq": "/steampulse/{env}/messaging/app-crawl-dlq-arn",
        "review-crawl-dlq": "/steampulse/{env}/messaging/review-crawl-dlq-arn",
        "spoke-results-dlq": "/steampulse/{env}/messaging/spoke-results-dlq-arn",
        "email-dlq": "/steampulse/{env}/messaging/email-dlq-arn",
    }

    TOPIC_PARAMS = {
        "game-events": "/steampulse/{env}/messaging/game-events-topic-arn",
        "content-events": "/steampulse/{env}/messaging/content-events-topic-arn",
        "system-events": "/steampulse/{env}/messaging/system-events-topic-arn",
    }

    def __init__(self, env: str | None) -> None:
        self.env = env
        self._ssm_cache: dict[str, str] = {}
        self._clients: dict[str, object] = {}

    def _require_env(self) -> str:
        if self.env is None:
            raise AwsUnavailableError("Connect to staging/production for AWS ops")
        return self.env

    def _client(self, service: str, region: str = "us-west-2") -> object:
        """Get or create a boto3 client with short timeouts for TUI responsiveness."""
        self._require_env()
        key = f"{service}:{region}"
        if key not in self._clients:
            import boto3
            from botocore.config import Config

            cfg = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 1})
            self._clients[key] = boto3.client(service, region_name=region, config=cfg)
        return self._clients[key]

    @property
    def sqs(self) -> object:
        return self._client("sqs")

    @property
    def sns(self) -> object:
        return self._client("sns")

    @property
    def ssm(self) -> object:
        return self._client("ssm")

    @property
    def sfn(self) -> object:
        return self._client("stepfunctions")

    def logs_for_region(self, region: str) -> object:
        """Get or create a CloudWatch Logs client for a specific region."""
        return self._client("logs", region)

    @property
    def logs(self) -> object:
        """Default CloudWatch Logs client (us-west-2)."""
        return self.logs_for_region("us-west-2")

    def resolve_ssm(self, param_name: str) -> str:
        """Resolve an SSM parameter, with caching."""
        if param_name not in self._ssm_cache:
            result = self.ssm.get_parameter(Name=param_name)  # type: ignore[union-attr]
            self._ssm_cache[param_name] = result["Parameter"]["Value"]
        return self._ssm_cache[param_name]

    def get_queue_url(self, name: str) -> str | None:
        """Resolve a queue URL from SSM. Returns None if param not found."""
        env = self._require_env()
        params = self.QUEUE_PARAMS | self.DLQ_PARAMS
        template = params.get(name)
        if not template:
            return None
        try:
            value = self.resolve_ssm(template.format(env=env))
            # If it's an ARN, derive the URL from it
            if value.startswith("arn:aws:sqs:"):
                parts = value.split(":")
                region = parts[3]
                account = parts[4]
                queue_name = parts[5]
                return f"https://sqs.{region}.amazonaws.com/{account}/{queue_name}"
            return value
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _region_from_queue_url(queue_url: str) -> str:
        """Extract region from an SQS queue URL like https://sqs.us-east-1.amazonaws.com/..."""
        try:
            host = queue_url.split("/")[2]  # sqs.us-east-1.amazonaws.com
            return host.split(".")[1]
        except (IndexError, AttributeError):
            return "us-west-2"

    def get_queue_depth(self, queue_url: str) -> dict[str, int]:
        """Get message counts for a queue, using the correct regional SQS client."""
        region = self._region_from_queue_url(queue_url)
        sqs_client = self._client("sqs", region)
        result = sqs_client.get_queue_attributes(  # type: ignore[union-attr]
            QueueUrl=queue_url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            ],
        )
        attrs = result.get("Attributes", {})
        return {
            "available": int(attrs.get("ApproximateNumberOfMessages", 0)),
            "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
            "delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0)),
        }

    _ERR_DEPTH: dict[str, int] = {"available": -1, "in_flight": -1, "delayed": -1}

    def get_all_queue_depths(self) -> dict[str, dict[str, int]]:
        """Get depths for all known queues + DLQs + spoke queues."""
        depths: dict[str, dict[str, int]] = {}

        # Static queues from SSM
        for name in list(self.QUEUE_PARAMS) + list(self.DLQ_PARAMS):
            url = self.get_queue_url(name)
            if url:
                try:
                    depths[name] = self.get_queue_depth(url)
                except Exception:  # noqa: BLE001
                    depths[name] = self._ERR_DEPTH
            else:
                depths[name] = self._ERR_DEPTH

        # Per-region spoke crawl queues (deterministic naming)
        env = self._require_env()
        spoke_regions = self._get_spoke_regions()
        account_id = self._get_account_id()
        if account_id:
            for region in spoke_regions:
                name = f"spoke-crawl-{region}"
                queue_name = f"steampulse-spoke-crawl-{region}-{env}"
                url = f"https://sqs.{region}.amazonaws.com/{account_id}/{queue_name}"
                try:
                    depths[name] = self.get_queue_depth(url)
                except Exception:  # noqa: BLE001
                    depths[name] = self._ERR_DEPTH

        return depths

    def _get_account_id(self) -> str | None:
        """Get AWS account ID from STS, cached."""
        if not hasattr(self, "_account_id"):
            try:
                sts = self._client("sts")
                self._account_id: str | None = sts.get_caller_identity()["Account"]  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                self._account_id = None
        return self._account_id

    def _get_spoke_regions(self) -> list[str]:
        """Get spoke regions from SPOKE_REGIONS env var."""
        import os

        regions_str = os.environ.get("SPOKE_REGIONS", "")
        return [r.strip() for r in regions_str.split(",") if r.strip()]

    def get_topic_arn(self, name: str) -> str | None:
        """Resolve a topic ARN from SSM."""
        env = self._require_env()
        template = self.TOPIC_PARAMS.get(name)
        if not template:
            return None
        try:
            return self.resolve_ssm(template.format(env=env))
        except Exception:  # noqa: BLE001
            return None

    def get_sfn_arn(self) -> str | None:
        """Resolve the Step Functions ARN from SSM."""
        env = self._require_env()
        try:
            return self.resolve_ssm(f"/steampulse/{env}/compute/sfn-arn")
        except Exception:  # noqa: BLE001
            return None

    def start_sfn_execution(self, input_json: str) -> str:
        """Start a Step Functions execution. Returns execution ARN."""
        arn = self.get_sfn_arn()
        if not arn:
            raise AwsUnavailableError("Could not resolve Step Functions ARN")
        result = self.sfn.start_execution(  # type: ignore[union-attr]
            stateMachineArn=arn,
            input=input_json,
        )
        return result["executionArn"]

    def publish_event(self, topic_name: str, event: object) -> str:
        """Publish a typed event to an SNS topic. Returns message ID."""
        from library_layer.utils.events import publish_event

        topic_arn = self.get_topic_arn(topic_name)
        if not topic_arn:
            raise AwsUnavailableError(f"Could not resolve topic ARN for {topic_name}")
        return publish_event(self.sns, topic_arn, event)  # type: ignore[arg-type]

    def send_sqs_message(self, queue_name: str, message_body: str) -> None:
        """Send a single message to an SQS queue."""
        url = self.get_queue_url(queue_name)
        if not url:
            raise AwsUnavailableError(f"Could not resolve queue URL for {queue_name}")
        self.sqs.send_message(QueueUrl=url, MessageBody=message_body)  # type: ignore[union-attr]
