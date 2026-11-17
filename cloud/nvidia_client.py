"""Production NVIDIA NIM Cloud Datacenter inference client for SunRoute cloud tier.

Implements CloudInferenceClient protocol using NVIDIA NIM API (https://integrate.api.nvidia.com/v1).
Falls back transparently to MockCloudClient if network fails or quota is exhausted.
All energy metrics are strictly labelled '_estimated' per Section 3.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

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

logger = logging.getLogger("cloud.nvidia_nim")


def _load_dotenv_if_present(env_path: str = ".env") -> None:
    """Lightweight .env loader without external dependencies."""
    if os.path.exists(env_path):
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("\"'")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


_load_dotenv_if_present()


class NvidiaNimClient(CloudInferenceClient):
    """Production Cloud Client backed by NVIDIA NIM Cloud Datacenter GPUs."""

    def __init__(
        self,
        api_key: str | None = None,
        model_id: str | None = None,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        timeout_s: float = 25.0,
        fallback_to_mock: bool = True,
    ) -> None:
        _load_dotenv_if_present()
        self.api_key = api_key or os.environ.get("NVIDIA_API_KEY", "")
        # High-speed production model on NVIDIA NIM (0.4s response, direct text generation)
        self.model_id = model_id or os.environ.get(
            "NVIDIA_MODEL_ID", "nvidia/nemotron-3.5-bolt-e4b"
        )
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.fallback_to_mock = fallback_to_mock
        self.mock_fallback = MockCloudClient() if fallback_to_mock else None
        self._http_client: httpx.AsyncClient | None = None

        if self.api_key:
            logger.info(
                "Initialized NVIDIA NIM Datacenter client for model %s at %s",
                self.model_id,
                self.base_url,
            )
        else:
            logger.warning("NVIDIA_API_KEY is not set. NVIDIA NIM client will use fallback.")

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        return self._http_client

    def health(self) -> dict[str, Any]:
        """Return health status and configuration."""
        return {
            "status": "healthy" if bool(self.api_key) else "degraded",
            "provider": "nvidia_nim",
            "model_id": self.model_id,
            "fallback_enabled": self.fallback_to_mock,
        }

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Execute inference on NVIDIA NIM cloud datacenter GPUs with fallback."""
        if not self.api_key:
            if self.mock_fallback:
                return await self.mock_fallback.infer(request)
            raise RuntimeError("NVIDIA_API_KEY is not configured and fallback is disabled.")

        t0 = time.perf_counter()
        try:
            client = await self._get_http_client()
            # Parse conversation messages if formatted as multi-turn turns
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are the central cloud AI assistant in the SunRoute "
                        "solar microgrid system, running on high-performance datacenter GPUs. "
                        "You deliver thorough, fluent, and comprehensive responses for "
                        "all inquiries, essays, detailed explanations, and multilingual "
                        "queries (including Marathi and Hindi) with high accuracy and depth."
                    ),
                }
            ]

            lines = request.prompt.strip().split("\n")
            current_role = "user"
            current_buffer: list[str] = []

            for line in lines:
                if line.startswith("User:"):
                    if current_buffer:
                        messages.append(
                            {"role": current_role, "content": "\n".join(current_buffer).strip()}
                        )
                        current_buffer = []
                    current_role = "user"
                    current_buffer.append(line[len("User:") :].strip())
                elif line.startswith("Assistant:"):
                    if current_buffer:
                        messages.append(
                            {"role": current_role, "content": "\n".join(current_buffer).strip()}
                        )
                        current_buffer = []
                    current_role = "assistant"
                    current_buffer.append(line[len("Assistant:") :].strip())
                else:
                    current_buffer.append(line)

            if current_buffer:
                messages.append(
                    {"role": current_role, "content": "\n".join(current_buffer).strip()}
                )

            if len(messages) == 1:
                messages.append({"role": "user", "content": request.prompt})

            max_tokens = min(max(request.max_output_tokens * 2, 768), 2048)
            payload = {
                "model": self.model_id,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.5,
            }

            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            choice = data["choices"][0]["message"]
            text = (choice.get("content") or choice.get("reasoning_content") or "").strip()
            if not text:
                text = "No content generated."

            exec_time_ms = (time.perf_counter() - t0) * 1000.0

            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", request.prompt_tokens_est)
            output_tokens = usage.get("completion_tokens", max(1, len(text.split())))

            # Datacenter estimated energy: ~7.2 J/token baseline for DGX/H100 blade
            energy_j = (prompt_tokens + output_tokens) * 7.2

            clean_model = self.model_id.split("/")[-1]
            return InferenceResponse(
                request_id=request.request_id,
                node_id="nvidia-nim-datacenter",
                text=f"[NVIDIA NIM Central Cloud - {clean_model}]\n\n{text}",
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                latency_ms=round(exec_time_ms, 2),
                energy_consumed_j_est=round(energy_j, 2),
            )

        except Exception as e:
            logger.warning("NVIDIA NIM API call failed (%s). Delegating to fallback.", e)
            if self.mock_fallback:
                return await self.mock_fallback.infer(request)
            raise RuntimeError(f"NVIDIA NIM call failed and fallback disabled: {e}") from e

    async def get_state(self) -> NodeState:
        """Return telemetry and health status of the NVIDIA cloud datacenter."""
        return NodeState(
            node_id="nvidia-nim-datacenter",
            city="city-01",  # Co-located with central cloud data center in Mumbai
            kind=NodeKind.CLOUD,
            models=[self.model_id],
            free_mem_mb=80000,
            gpu_util=0.35,
            queue_depth=1,
            temp_c=41.0,
            battery_soc=1.0,  # Grid powered datacenter
            solar_w=0.0,
            wind_w=0.0,
            load_w=350.0,  # NVIDIA DGX H100 blade baseline (W)
            connectivity=ConnectivityStatus.ONLINE
            if bool(self.api_key)
            else ConnectivityStatus.DEGRADED,
            energy_source=EnergySource.SIMULATED,
        )

    async def close(self) -> None:
        """Close the HTTP client session."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
