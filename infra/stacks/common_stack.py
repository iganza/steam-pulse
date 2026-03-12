"""CommonStack — shared Lambda layers published once, referenced by all stacks."""
import aws_cdk as cdk
import aws_cdk.aws_lambda as lambda_
from aws_cdk.aws_lambda_python_alpha import PythonLayerVersion
from constructs import Construct


class CommonStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.library_layer = PythonLayerVersion(
            self,
            "LibraryLayer",
            entry="src/library-layer",
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Shared deps (httpx, psycopg2, boto3, anthropic) + steampulse framework",
        )
