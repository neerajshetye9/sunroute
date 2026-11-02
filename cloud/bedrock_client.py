"""Production AWS Bedrock inference client for SunRoute cloud fallback tier.

Implements CloudInferenceClient protocol using boto3 bedrock-runtime.
Falls back transparently to MockCloudClient if credentials or models are unavailable.
All energy metrics are strictly labelled '_estimated' per Section 3.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from cloud.interface import CloudInferenceClient
from cloud.mock_client import MockCloudClient
from edge.schemas import (
    ConnectivityStatus,
    EnergySource,
    InferenceRequest,
    InferenceResponse,
    NodeKind,
    NodeState,
)

logger = logging.getLogger("cloud.bedrock")


class BedrockCloudClient(CloudInferenceClient):
    """Production Cloud Client backed by AWS Bedrock Runtime."""

    def __init__(
        self,
        model_id: str = "amazon.titan-text-express-v1",
        region_name: str | None = None,
        fallback_to_mock: bool = True,
    ) -> None:
        self.model_id = model_id
        self.region = region_name or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self.fallback_to_mock = fallback_to_mock
        self.mock_fallback = MockCloudClient() if fallback_to_mock else None

        self._client: Any = None
        self._init_bedrock_client()

    def _init_bedrock_client(self) -> None:
        try:
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        except Exception as e:
            logger.warning("Failed to initialize Bedrock client: %s", e)
            self._client = None

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Execute inference on AWS Bedrock or fallback."""
        if self._client is None and self.mock_fallback:
            return await self.mock_fallback.infer(request)

        t0 = time.perf_counter()
        try:
            # Prepare request payload depending on model family
            if "titan" in self.model_id:
                body = json.dumps(
                    {
                        "inputText": request.prompt,
                        "textGenerationConfig": {
                            "maxTokenCount": request.max_output_tokens,
                            "temperature": 0.7,
                        },
                    }
                )
            elif "anthropic" in self.model_id:
                body = json.dumps(
                    {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": request.max_output_tokens,
                        "messages": [{"role": "user", "content": request.prompt}],
                    }
                )
            else:  # Generic Llama / Mistral prompt
                body = json.dumps(
                    {
                        "prompt": request.prompt,
                        "max_gen_len": request.max_output_tokens,
                        "temperature": 0.7,
                    }
                )

            response = self._client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            response_body = json.loads(response["body"].read())
            exec_time_ms = (time.perf_counter() - t0) * 1000.0

            # Extract generated text
            if "titan" in self.model_id:
                text = response_body.get("results", [{}])[0].get("outputText", "")
            elif "anthropic" in self.model_id:
                text = response_body.get("content", [{}])[0].get("text", "")
            else:
                text = response_body.get("generation", "")

            tokens_generated = max(1, len(text.split()))

            # Datacenter estimated energy: ~7.2 J/token (0.002 Wh/token datacenter baseline)
            energy_j = (request.prompt_tokens_est + tokens_generated) * 7.2

            return InferenceResponse(
                request_id=request.request_id,
                node_id="aws-bedrock-datacenter",
                text=text.strip(),
                prompt_tokens=request.prompt_tokens_est,
                output_tokens=tokens_generated,
                latency_ms=round(exec_time_ms, 2),
                energy_consumed_j_est=round(energy_j, 2),
            )

        except (ClientError, BotoCoreError, Exception) as e:
            logger.warning("AWS Bedrock call failed (%s). Checking fallback.", e)
            if self.mock_fallback:
                return await self.mock_fallback.infer(request)
            raise RuntimeError(f"Bedrock invocation failed and fallback disabled: {e}") from e

    def get_state(self) -> NodeState:
        """Return cloud node state."""
        return NodeState(
            node_id="aws-bedrock-datacenter",
            city="city-01",  # Co-located with central cloud data center
            kind=NodeKind.CLOUD,
            models=[self.model_id],
            free_mem_mb=128000,
            gpu_util=0.25,
            queue_depth=0,
            temp_c=42,
            battery_soc=1.0,  # Grid powered
            solar_w=0.0,
            wind_w=0.0,
            load_w=280.0,  # Cloud server blade baseline
            connectivity=ConnectivityStatus.ONLINE
            if self._client is not None
            else ConnectivityStatus.DEGRADED,
            energy_source=EnergySource.SIMULATED,
        )

    def health(self) -> dict[str, Any]:
        """Health check for Bedrock connection."""
        return {
            "status": "healthy" if self._client is not None else "degraded",
            "model_id": self.model_id,
            "region": self.region,
            "has_credentials": self._client is not None,
            "fallback_enabled": self.fallback_to_mock,
        }
