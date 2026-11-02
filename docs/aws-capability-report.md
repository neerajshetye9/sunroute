# AWS Capability and Permission Audit Report

- **Generated at**: `2026-11-02T14:42:51.400613+00:00`
- **Region**: `us-east-1`
- **Verdict**: `NO_CREDENTIALS`

## 1. Identity & Authentication

> [!WARNING]
> No active AWS lab credentials found in environment.
> The system will operate with calibrated `MockCloudClient` fallback.

## 2. Service Accessibility Matrix

| Service | Required For | Status | Details / Permissions |
|---|---|---|---|
| **AWS BEDROCK** | Cloud heavy inference fallback | `MOCK_FALLBACK` | Using local mock client with datacenter latency/energy calibration |
| **AWS LAMBDA** | Serverless telemetry ingest & processing | `MOCK_FALLBACK` | Using local mock client with datacenter latency/energy calibration |
| **AWS SQS** | Durable telemetry buffer queue | `MOCK_FALLBACK` | Using local mock client with datacenter latency/energy calibration |
| **AWS DYNAMODB** | Latest node state store & deduplication | `MOCK_FALLBACK` | Using local mock client with datacenter latency/energy calibration |
| **AWS S3** | Raw telemetry archive & Parquet datasets | `MOCK_FALLBACK` | Using local mock client with datacenter latency/energy calibration |
| **AWS CLOUDWATCH** | Metrics logging and latency alarms | `MOCK_FALLBACK` | Using local mock client with datacenter latency/energy calibration |

## 3. Operational Strategy & Architecture Decision

Per CLAUDE.md Section 3 & Rule 7:
- If AWS Bedrock is available: `BedrockCloudClient` invokes cloud models.
- If credentials are absent/restricted: `MockCloudClient` fallback is used.
- Every metric is labelled `_estimated` and `_simulated` per Section 3.
- No hard crash occurs; local evaluation loops remain 100% operational.
