"""ApplicationStage — wires all stacks in lifecycle order.

Stack deployment order:
  NetworkStack  ──────────────────────────────────────────────────────┐
  DataStack      (needs vpc, intra_sg from Network)                    │
  MessagingStack (no VPC dependency — SQS is fully managed)            │
  ComputeStack   (needs Network + Data + Messaging)                    │
  CertificateStack (production only — us-east-1, ACM for CloudFront)  │
  DeliveryStack  (needs Compute fn URLs + Certificate if production)   │
  FrontendStack  (looks up assets bucket by name)                       │
  MonitoringStack (reads ARNs from SSM — no hard CF dependency)        │

Config is loaded from .env.{environment} at synth time and passed through
constructors — the CDK best-practice approach.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "library-layer"))

import aws_cdk as cdk
from constructs import Construct
from library_layer.config import SteamPulseConfig
from stacks.batch_analysis_stack import BatchAnalysisStack
from stacks.certificate_stack import CertificateStack
from stacks.compute_stack import ComputeStack
from stacks.data_stack import DataStack
from stacks.delivery_stack import DeliveryStack
from stacks.frontend_stack import FrontendStack
from stacks.messaging_stack import MessagingStack
from stacks.network_stack import NetworkStack
from stacks.spoke_stack import CrawlSpokeStack

# from stacks.monitoring_stack import MonitoringStack


class ApplicationStage(cdk.Stage):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        config = SteamPulseConfig.for_environment(environment)
        env_name = environment.capitalize()
        cdk_env = cdk.Environment(account=self.account, region=self.region)

        # ── Network ───────────────────────────────────────────────────────────
        network = NetworkStack(
            self,
            "Network",
            stack_name=f"SteamPulse-{env_name}-Network",
            config=config,
            termination_protection=config.is_production,
            env=cdk_env,
        )

        # ── Data ──────────────────────────────────────────────────────────────
        data = DataStack(
            self,
            "Data",
            stack_name=f"SteamPulse-{env_name}-Data",
            config=config,
            vpc=network.vpc,
            intra_sg=network.intra_sg,
            nat_sg=network.nat_sg,
            termination_protection=config.is_production,
            env=cdk_env,
        )
        data.add_dependency(network)

        # ── Messaging ─────────────────────────────────────────────────────────
        messaging = MessagingStack(
            self,
            "Messaging",
            stack_name=f"SteamPulse-{env_name}-Messaging",
            config=config,
            env=cdk_env,
        )

        # ── Per-spoke crawl queue URLs (deterministic, for cross-region SQS send)
        acct = self.account
        spoke_crawl_queue_urls = ",".join(
            f"https://sqs.{region}.amazonaws.com/{acct}"
            f"/steampulse-spoke-crawl-{region}-{environment}"
            for region in config.spoke_region_list
        )

        # ── Compute ───────────────────────────────────────────────────────────
        compute = ComputeStack(
            self,
            "Compute",
            stack_name=f"SteamPulse-{env_name}-Compute",
            config=config,
            vpc=network.vpc,
            intra_sg=network.intra_sg,
            db_secret=data.db_secret,
            app_crawl_queue=messaging.app_crawl_queue,
            review_crawl_queue=messaging.review_crawl_queue,
            game_events_topic=messaging.game_events_topic,
            content_events_topic=messaging.content_events_topic,
            system_events_topic=messaging.system_events_topic,
            spoke_results_queue=messaging.spoke_results_queue,
            email_queue=messaging.email_queue,
            spoke_crawl_queue_urls=spoke_crawl_queue_urls,
            env=cdk_env,
        )
        compute.add_dependency(data)
        compute.add_dependency(messaging)

        # ── Certificate (production only — must be in us-east-1 for CloudFront)
        if config.is_production:
            cert_stack = CertificateStack(
                self,
                "Certificate",
                stack_name=f"SteamPulse-{env_name}-Certificate",
                config=config,
                env=cdk.Environment(account=self.account, region="us-east-1"),
            )
            certificate = cert_stack.certificate
        else:
            cert_stack = None
            certificate = None

        # ── Delivery ──────────────────────────────────────────────────────────
        delivery = DeliveryStack(
            self,
            "Delivery",
            stack_name=f"SteamPulse-{env_name}-Delivery",
            config=config,
            api_fn_url=compute.api_fn_url,
            frontend_fn_url=compute.frontend_fn_url,
            certificate=certificate,
            env=cdk_env,
        )
        delivery.add_dependency(compute)
        if cert_stack is not None:
            delivery.add_dependency(cert_stack)

        # ── Frontend ──────────────────────────────────────────────────────────
        frontend = FrontendStack(
            self,
            "Frontend",
            stack_name=f"SteamPulse-{env_name}-Frontend",
            config=config,
            env=cdk_env,
        )
        frontend.add_dependency(delivery)

        # ── Batch Analysis ────────────────────────────────────────────────────
        batch = BatchAnalysisStack(
            self,
            "BatchAnalysis",
            stack_name=f"SteamPulse-{env_name}-BatchAnalysis",
            config=config,
            vpc=network.vpc,
            intra_sg=network.intra_sg,
            db_secret=data.db_secret,
            content_events_topic=messaging.content_events_topic,
            system_events_topic=messaging.system_events_topic,
            env=cdk_env,
        )
        batch.add_dependency(compute)
        batch.add_dependency(messaging)

        # ── Monitoring ────────────────────────────────────────────────────────
        # Disabled — enable when ready to set up alarms.
        # MonitoringStack(
        #     self, "Monitoring",
        #     stack_name=f"SteamPulse-{env_name}-Monitoring",
        #     config=config,
        #     env=cdk_env,
        # )

        # ── Spoke Stacks (one per region) ─────────────────────────────────
        # Every region is a spoke, including the primary. Spoke Lambdas
        # fetch from Steam → S3 → SQS → IngestFn (primary region, above).
        # Plain strings — CDK tokens can't cross regions. Queues + bucket
        # have deterministic physical names for this reason.
        steam_secret_name = f"steampulse/{environment}/steam-api-key"
        primary_region = self.region
        results_q_name = f"steampulse-spoke-results-{environment}"
        bucket_name = f"steampulse-assets-{environment}"

        for region in config.spoke_region_list:
            spoke = CrawlSpokeStack(
                self,
                f"Spoke-{region}",
                stack_name=f"SteamPulse-{env_name}-Spoke-{region}",
                config=config,
                primary_region=primary_region,
                environment=environment,
                spoke_results_queue_url=f"https://sqs.{primary_region}.amazonaws.com/{acct}/{results_q_name}",
                assets_bucket_name=bucket_name,
                steam_api_key_secret_name=steam_secret_name,
                env=cdk.Environment(account=self.account, region=region),
            )
            spoke.add_dependency(messaging)
            spoke.add_dependency(data)
