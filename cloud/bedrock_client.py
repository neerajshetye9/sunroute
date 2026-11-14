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
        model_id: str = "anthropic.claude-3-haiku-20240307-v1:0",
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
            aws_key = os.environ.get("AWS_ACCESS_KEY_ID")
            aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
            aws_session = os.environ.get("AWS_SESSION_TOKEN")

            kwargs: dict[str, Any] = {"region_name": self.region}
            if aws_key and aws_secret:
                kwargs["aws_access_key_id"] = aws_key
                kwargs["aws_secret_access_key"] = aws_secret
                if aws_session:
                    kwargs["aws_session_token"] = aws_session

            self._client = boto3.client("bedrock-runtime", **kwargs)
            logger.info(
                "Initialized AWS Bedrock client in region %s for model %s",
                self.region,
                self.model_id,
            )
        except Exception as e:
            logger.warning("Failed to initialize Bedrock client: %s. Using fallback.", e)
            self._client = None

    def health(self) -> dict[str, Any]:
        """Return health status and fallback availability."""
        return {
            "status": "healthy" if self._client is not None else "degraded",
            "fallback_enabled": self.fallback_to_mock,
            "model_id": self.model_id,
            "region": self.region,
        }

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Execute inference on AWS Bedrock or fallback."""
        if self._client is None:
            if self.mock_fallback:
                return await self.mock_fallback.infer(request)
            raise RuntimeError("Bedrock client is not configured and mock fallback is disabled.")

        t0 = time.perf_counter()
        try:
            # Prepare request payload depending on model family
            if "claude" in self.model_id or "anthropic" in self.model_id:
                body = json.dumps(
                    {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": min(request.max_output_tokens * 2, 1024),
                        "messages": [{"role": "user", "content": request.prompt}],
                    }
                )
            elif "titan" in self.model_id:
                body = json.dumps(
                    {
                        "inputText": request.prompt,
                        "textGenerationConfig": {
                            "maxTokenCount": min(request.max_output_tokens * 2, 1024),
                            "temperature": 0.7,
                        },
                    }
                )
            else:  # Generic Llama / Mistral prompt
                body = json.dumps(
                    {
                        "prompt": request.prompt,
                        "max_gen_len": min(request.max_output_tokens * 2, 1024),
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
            if "claude" in self.model_id or "anthropic" in self.model_id:
                content_blocks = response_body.get("content", [])
                text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
            elif "titan" in self.model_id:
                text = response_body.get("results", [{}])[0].get("outputText", "")
            else:
                text = response_body.get("generation", "")

            tokens_generated = max(1, len(text.split()))

            # Datacenter estimated energy: ~7.2 J/token (0.002 Wh/token datacenter baseline)
            energy_j = (request.prompt_tokens_est + tokens_generated) * 7.2

            return InferenceResponse(
                request_id=request.request_id,
                node_id="aws-bedrock-datacenter",
                text=f"[AWS Bedrock Central - {self.model_id}]\n\n{text.strip()}",
                prompt_tokens=request.prompt_tokens_est,
                output_tokens=tokens_generated,
                latency_ms=round(exec_time_ms, 2),
                energy_consumed_j_est=round(energy_j, 2),
            )

        except (ClientError, BotoCoreError, Exception) as e:
            logger.warning("AWS Bedrock call failed (%s). Delegating to fallback.", e)
            if self.mock_fallback:
                return await self.mock_fallback.infer(request)
            raise RuntimeError(f"Bedrock invocation failed and fallback disabled: {e}") from e

    def get_state(self) -> NodeState:
        """Return cloud node state."""
        return NodeState(
            node_id="aws-bedrock-datacenter",
            city="city-01",  # Co-located with central cloud data center in Mumbai
            kind=NodeKind.CLOUD,
            models=[self.model_id],
            free_mem_mb=128000,
            gpu_util=0.25,
            queue_depth=1,
            temp_c=42.0,
            battery_soc=1.0,  # Grid powered
            solar_w=0.0,
            wind_w=0.0,
            load_w=250.0,  # Cloud server blade baseline (W)
            connectivity=ConnectivityStatus.ONLINE
            if self._client is not None
            else ConnectivityStatus.DEGRADED,
            energy_source=EnergySource.SIMULATED,
        )
