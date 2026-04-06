"""AWS client wrappers for the TUI — SQS, SNS, SSM, SFN, CloudWatch Logs."""


class AwsUnavailableError(Exception):
    """Raised when AWS operations are attempted without --env."""


class AwsClients:
    """Lazy-init boto3 clients with SSM parameter caching."""

    QUEUE_PARAMS = {
        "app-crawl-queue": "/steampulse/{env}/messaging/app-crawl-queue-url",
        "review-crawl-queue": "/steampulse/{env}/messaging/review-crawl-queue-url",
        "spoke-results-queue": "/steampulse/{env}/messaging/spoke-results-queue-arn",
        "cache-invalidation-queue": "/steampulse/{env}/messaging/cache-invalidation-queue-url",
        "email-queue": "/steampulse/{env}/messaging/email-queue-arn",
    }

    DLQ_PARAMS = {
        "metadata-dlq": "/steampulse/{env}/messaging/metadata-dlq-arn",
        "review-dlq": "/steampulse/{env}/messaging/review-dlq-arn",
        "spoke-results-dlq": "/steampulse/{env}/messaging/spoke-results-dlq-arn",
        "cache-dlq": "/steampulse/{env}/messaging/cache-dlq-arn",
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
        """Get or create a boto3 client."""
        self._require_env()
        key = f"{service}:{region}"
        if key not in self._clients:
            import boto3

            self._clients[key] = boto3.client(service, region_name=region)
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

    @property
    def logs(self) -> object:
        return self._client("logs")

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

    def get_queue_depth(self, queue_url: str) -> dict[str, int]:
        """Get message counts for a queue."""
        result = self.sqs.get_queue_attributes(  # type: ignore[union-attr]
            QueueUrl=queue_url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
            ],
        )
        attrs = result.get("Attributes", {})
        return {
            "messages": int(attrs.get("ApproximateNumberOfMessages", 0)),
            "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
        }

    def get_all_queue_depths(self) -> dict[str, dict[str, int]]:
        """Get depths for all known queues + DLQs."""
        depths: dict[str, dict[str, int]] = {}
        for name in list(self.QUEUE_PARAMS) + list(self.DLQ_PARAMS):
            url = self.get_queue_url(name)
            if url:
                try:
                    depths[name] = self.get_queue_depth(url)
                except Exception:  # noqa: BLE001
                    depths[name] = {"messages": -1, "in_flight": -1}
            else:
                depths[name] = {"messages": -1, "in_flight": -1}
        return depths

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
