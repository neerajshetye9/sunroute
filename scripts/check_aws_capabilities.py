"""Audit script checking AWS permissions and capabilities for SunRoute.

Checks STS identity, Bedrock models, Lambda, SQS, DynamoDB, S3, and CloudWatch.
Generates docs/aws-capability-report.md.
Adheres to Rule 7 (Never invent AWS capabilities: check or report fallback).
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("aws_audit")


class AWSCapabilityChecker:
    """Safe, non-destructive auditor of AWS permissions."""

    def __init__(self, region_name: str | None = None) -> None:
        self.region = region_name or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self.session = boto3.Session(region_name=self.region)
        self.results: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "region": self.region,
            "has_credentials": False,
            "identity": None,
            "services": {},
            "verdict": "UNKNOWN",
        }

    def run_checks(self) -> dict[str, Any]:
        """Execute all non-destructive permission probes."""
        # 1. Check STS Identity
        try:
            sts = self.session.client("sts")
            identity = sts.get_caller_identity()
            self.results["has_credentials"] = True
            self.results["identity"] = {
                "account": identity.get("Account"),
                "arn": identity.get("Arn"),
                "user_id": identity.get("UserId"),
            }
            logger.info("Authenticated as: %s", identity.get("Arn"))
        except (NoCredentialsError, PartialCredentialsError) as e:
            logger.warning("AWS credentials not found: %s", e)
            self.results["verdict"] = "NO_CREDENTIALS"
            self.results["error"] = str(e)
            return self.results
        except Exception as e:
            logger.warning("STS Caller Identity check failed: %s", e)
            self.results["verdict"] = "AUTH_FAILED"
            self.results["error"] = str(e)
            return self.results

        # 2. Probe Bedrock
        self._check_bedrock()

        # 3. Probe Lambda
        self._check_lambda()

        # 4. Probe SQS
        self._check_sqs()

        # 5. Probe DynamoDB
        self._check_dynamodb()

        # 6. Probe S3
        self._check_s3()

        # 7. Probe CloudWatch
        self._check_cloudwatch()

        # Determine overall verdict
        accessible_services = sum(
            1 for s in self.results["services"].values() if s.get("status") == "AVAILABLE"
        )
        total_services = len(self.results["services"])
        if accessible_services == total_services:
            self.results["verdict"] = "FULL_ACCESS"
        elif accessible_services > 0:
            self.results["verdict"] = "PARTIAL_ACCESS"
        else:
            self.results["verdict"] = "NO_SERVICES_ACCESSIBLE"

        return self.results

    def _check_bedrock(self) -> None:
        try:
            bedrock = self.session.client("bedrock")
            models_resp = bedrock.list_foundation_models()
            models = [m["modelId"] for m in models_resp.get("modelSummaries", [])[:10]]
            self.results["services"]["bedrock"] = {
                "status": "AVAILABLE",
                "sample_models": models,
                "model_count": len(models_resp.get("modelSummaries", [])),
            }
        except Exception as e:
            self.results["services"]["bedrock"] = {
                "status": "RESTRICTED",
                "error": str(e),
            }

    def _check_lambda(self) -> None:
        try:
            lmb = self.session.client("lambda")
            funcs = lmb.list_functions(MaxItems=5)
            self.results["services"]["lambda"] = {
                "status": "AVAILABLE",
                "function_count": len(funcs.get("Functions", [])),
            }
        except Exception as e:
            self.results["services"]["lambda"] = {
                "status": "RESTRICTED",
                "error": str(e),
            }

    def _check_sqs(self) -> None:
        try:
            sqs = self.session.client("sqs")
            queues = sqs.list_queues(MaxResults=5)
            self.results["services"]["sqs"] = {
                "status": "AVAILABLE",
                "queue_urls": queues.get("QueueUrls", []),
            }
        except Exception as e:
            self.results["services"]["sqs"] = {
                "status": "RESTRICTED",
                "error": str(e),
            }

    def _check_dynamodb(self) -> None:
        try:
            ddb = self.session.client("dynamodb")
            tables = ddb.list_tables(Limit=5)
            self.results["services"]["dynamodb"] = {
                "status": "AVAILABLE",
                "tables": tables.get("TableNames", []),
            }
        except Exception as e:
            self.results["services"]["dynamodb"] = {
                "status": "RESTRICTED",
                "error": str(e),
            }

    def _check_s3(self) -> None:
        try:
            s3 = self.session.client("s3")
            buckets = s3.list_buckets()
            self.results["services"]["s3"] = {
                "status": "AVAILABLE",
                "bucket_count": len(buckets.get("Buckets", [])),
            }
        except Exception as e:
            self.results["services"]["s3"] = {
                "status": "RESTRICTED",
                "error": str(e),
            }

    def _check_cloudwatch(self) -> None:
        try:
            cw = self.session.client("cloudwatch")
            cw.list_metrics()
            self.results["services"]["cloudwatch"] = {
                "status": "AVAILABLE",
                "metrics_accessible": True,
            }
        except Exception as e:
            self.results["services"]["cloudwatch"] = {
                "status": "RESTRICTED",
                "error": str(e),
            }

    def generate_markdown_report(
        self, output_path: Path | str = "docs/aws-capability-report.md"
    ) -> str:
        """Format check findings as a markdown report."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            "# AWS Capability and Permission Audit Report",
            "",
            f"- **Generated at**: `{self.results['timestamp']}`",
            f"- **Region**: `{self.results['region']}`",
            f"- **Verdict**: `{self.results['verdict']}`",
            "",
            "## 1. Identity & Authentication",
            "",
        ]

        if self.results.get("has_credentials") and self.results.get("identity"):
            id_info = self.results["identity"]
            lines.extend(
                [
                    f"- **Account ID**: `{id_info.get('account')}`",
                    f"- **Caller ARN**: `{id_info.get('arn')}`",
                    f"- **User ID**: `{id_info.get('user_id')}`",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!WARNING]",
                    "> No active AWS lab credentials found in environment.",
                    "> The system will operate with calibrated `MockCloudClient` fallback.",
                ]
            )

        lines.extend(
            [
                "",
                "## 2. Service Accessibility Matrix",
                "",
                "| Service | Required For | Status | Details / Permissions |",
                "|---|---|---|---|",
            ]
        )

        service_roles = {
            "bedrock": "Cloud heavy inference fallback",
            "lambda": "Serverless telemetry ingest & processing",
            "sqs": "Durable telemetry buffer queue",
            "dynamodb": "Latest node state store & deduplication",
            "s3": "Raw telemetry archive & Parquet datasets",
            "cloudwatch": "Metrics logging and latency alarms",
        }

        for svc_name, role in service_roles.items():
            svc_info = self.results.get("services", {}).get(svc_name, {})
            status = svc_info.get(
                "status", "NOT_CHECKED" if self.results.get("has_credentials") else "MOCK_FALLBACK"
            )
            if status == "AVAILABLE":
                badge = "AVAILABLE"
                detail = "Permissions verified"
                if svc_name == "bedrock":
                    detail = f"{svc_info.get('model_count', 0)} models found"
                elif svc_name == "s3":
                    detail = f"{svc_info.get('bucket_count', 0)} buckets found"
            elif status == "RESTRICTED":
                badge = "RESTRICTED"
                detail = svc_info.get("error", "AccessDenied")[:60]
            else:
                badge = "MOCK_FALLBACK"
                detail = "Using local mock client with datacenter latency/energy calibration"

            lines.append(f"| **AWS {svc_name.upper()}** | {role} | `{badge}` | {detail} |")

        lines.extend(
            [
                "",
                "## 3. Operational Strategy & Architecture Decision",
                "",
                "Per CLAUDE.md Section 3 & Rule 7:",
                "- If AWS Bedrock is available: `BedrockCloudClient` invokes cloud models.",
                "- If credentials are absent/restricted: `MockCloudClient` fallback is used.",
                "- Every metric is labelled `_estimated` and `_simulated` per Section 3.",
                "- No hard crash occurs; local evaluation loops remain 100% operational.",
                "",
            ]
        )

        report_content = "\n".join(lines)
        with open(out, "w", encoding="utf-8") as f:
            f.write(report_content)

        return report_content


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit AWS permissions for SunRoute")
    parser.add_argument("--region", type=str, default=None, help="AWS region to probe")
    parser.add_argument(
        "--output",
        type=str,
        default="docs/aws-capability-report.md",
        help="Path to markdown output",
    )
    args = parser.parse_args()

    checker = AWSCapabilityChecker(region_name=args.region)
    results = checker.run_checks()
    checker.generate_markdown_report(output_path=args.output)
    print(f"Audit completed. Verdict: {results['verdict']}. Report written to {args.output}")


if __name__ == "__main__":
    main()
