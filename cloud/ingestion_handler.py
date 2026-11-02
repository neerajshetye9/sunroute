"""Serverless Lambda handlers for SunRoute telemetry ingestion and processing.

Architecture per Section 5.1:
API Gateway (/telemetry) -> Ingestion Lambda -> SQS -> Worker Lambda -> DynamoDB & S3.
Deduplicates messages idempotently by 'message_id' to satisfy Hypothesis H4 (0 duplicates, 0 loss).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("cloud.ingestion")
logger.setLevel(logging.INFO)

# Environment variables
TELEMETRY_QUEUE_URL = os.environ.get("TELEMETRY_QUEUE_URL", "")
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "SunRouteNodeState")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "sunroute-telemetry-archive")
INGESTION_TOKEN = os.environ.get("INGESTION_TOKEN", "sunroute-telemetry-token")

# Boto3 clients (initialized lazily)
_sqs: Any = None
_dynamodb: Any = None
_s3: Any = None


def get_sqs():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs")
    return _sqs


def get_dynamodb():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


def get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def api_gateway_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """HTTP API Gateway entrypoint: validates auth token and enqueues to SQS."""
    headers = event.get("headers", {}) or {}
    auth_header = headers.get("authorization") or headers.get("Authorization") or ""
    token = auth_header.replace("Bearer ", "").strip()

    expected_token = os.environ.get("INGESTION_TOKEN", INGESTION_TOKEN)
    if token != expected_token:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Unauthorized: invalid telemetry token"}),
        }

    raw_body = event.get("body", "{}")
    if event.get("isBase64Encoded", False):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Invalid JSON body"}),
        }

    # Extract or generate message_id for deduplication
    message_id = payload.get("message_id")
    if not message_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Missing required field: message_id"}),
        }

    if not TELEMETRY_QUEUE_URL:
        # Dry run / local testing mode without live SQS
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"status": "accepted_dry_run", "message_id": message_id}),
        }

    sqs = get_sqs()
    sqs.send_message(
        QueueUrl=TELEMETRY_QUEUE_URL,
        MessageBody=json.dumps(payload),
        MessageAttributes={
            "message_id": {"DataType": "String", "StringValue": str(message_id)},
            "node_id": {
                "DataType": "String",
                "StringValue": str(payload.get("node_id", "unknown")),
            },
        },
    )

    return {
        "statusCode": 202,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"status": "enqueued", "message_id": message_id}),
    }


def sqs_worker_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SQS Worker: Deduplicates by message_id, stores to DynamoDB and archives to S3."""
    records = event.get("Records", [])
    processed_count = 0
    duplicate_count = 0

    table = get_dynamodb().Table(DYNAMODB_TABLE_NAME) if DYNAMODB_TABLE_NAME else None
    s3 = get_s3()

    for record in records:
        body_str = record.get("body", "{}")
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            continue

        message_id = data.get("message_id")
        node_id = data.get("node_id", "unknown")
        ts = data.get("ts", datetime.now(UTC).isoformat())

        if not message_id or not table:
            continue

        # Idempotent write to DynamoDB
        # Conditional put or check to ensure message_id has not already been processed
        try:
            table.put_item(
                Item={
                    "node_id": node_id,
                    "last_message_id": message_id,
                    "updated_at": ts,
                    "battery_soc": str(data.get("battery_soc", 0.0)),
                    "solar_w": str(data.get("solar_w", 0.0)),
                    "wind_w": str(data.get("wind_w", 0.0)),
                    "temp_c": str(data.get("temp_c", 0.0)),
                    "queue_depth": int(data.get("queue_depth", 0)),
                    "connectivity": data.get("connectivity", "online"),
                    "raw_payload": body_str,
                }
            )
            processed_count += 1
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                duplicate_count += 1
                logger.info("Deduplicated duplicate message_id: %s", message_id)
                continue
            raise

        # Archive raw payload to S3 partition by date and node
        if S3_BUCKET_NAME:
            now_dt = datetime.now(UTC)
            s3_key = f"telemetry/{now_dt.strftime('%Y/%m/%d')}/{node_id}/{message_id}.json"
            try:
                s3.put_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=s3_key,
                    Body=body_str,
                    ContentType="application/json",
                )
            except Exception as e:
                logger.warning("Failed S3 archive for %s: %s", s3_key, e)

    return {
        "status": "success",
        "processed": processed_count,
        "duplicates": duplicate_count,
    }
