"""Cloud client factory for SunRoute.

Instantiates the active cloud inference client based on available environment credentials:
1. NVIDIA NIM (if NVIDIA_API_KEY is present)
2. AWS Bedrock (if AWS credentials / BEDROCK_API_URL is configured)
3. Calibrated Mock Cloud Client (fallback for offline evaluation)
"""

from __future__ import annotations

import logging
import os

from cloud.bedrock_client import BedrockCloudClient
from cloud.interface import CloudInferenceClient
from cloud.mock_client import MockCloudClient
from cloud.nvidia_client import NvidiaNimClient, _load_dotenv_if_present

logger = logging.getLogger("cloud.factory")


def get_cloud_client(fallback_to_mock: bool = True) -> CloudInferenceClient:
    """Return the appropriate cloud inference client based on environment."""
    _load_dotenv_if_present()

    nvidia_key = os.environ.get("NVIDIA_API_KEY")
    if nvidia_key:
        logger.info("Using NVIDIA NIM Cloud Datacenter client.")
        return NvidiaNimClient(fallback_to_mock=fallback_to_mock)

    aws_key = os.environ.get("AWS_ACCESS_KEY_ID")
    bedrock_url = os.environ.get("BEDROCK_API_URL")
    if aws_key or bedrock_url:
        logger.info("Using AWS Bedrock Central Cloud client.")
        return BedrockCloudClient(fallback_to_mock=fallback_to_mock)

    logger.info("No cloud credentials detected. Using calibrated Mock Cloud Client.")
    return MockCloudClient()
