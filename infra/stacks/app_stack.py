"""App stack skeleton — FastAPI Lambda + CloudFront. Phase 2 will flesh this out."""

import aws_cdk as cdk
from constructs import Construct

from stacks.data_stack import DataStack


class AppStack(cdk.Stack):
    def __init__(
        self, scope: Construct, construct_id: str, data_stack: DataStack, **kwargs: object
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # Phase 2: Lambda + CloudFront + Route53 + ACM added here
