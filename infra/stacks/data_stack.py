"""Data stack skeleton — RDS + S3. Phase 2 will flesh this out."""

import aws_cdk as cdk
from constructs import Construct


class DataStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # Phase 2: RDS PostgreSQL + S3 bucket added here
