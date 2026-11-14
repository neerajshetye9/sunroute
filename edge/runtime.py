"""Inference runtime backend for Edge Agent.

Connects to local llama.cpp server when running, with a calibrated local mock
for testing and emulation when the native server is not active.
"""

from __future__ import annotations

import logging
import time

import httpx

from edge.config import EdgeConfig
from edge.schemas import InferenceRequest, InferenceResponse

logger = logging.getLogger("edge_runtime")


class EdgeRuntime:
    """Manages inference execution and energy accounting."""

    def __init__(self, config: EdgeConfig):
        self.config = config
        self.http_client = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        await self.http_client.aclose()

    async def is_llama_server_alive(self) -> bool:
        """Check if local llama.cpp server is reachable."""
        try:
            res = await self.http_client.get(f"{self.config.llama_cpp_url}/health")
            return res.status_code == 200
        except Exception:
            return False

    async def infer(self, req: InferenceRequest, current_power_w: float) -> InferenceResponse:
        """Execute inference on the edge runtime."""
        start_time = time.time()

        # Check if llama.cpp server is active
        is_live = await self.is_llama_server_alive()

        if is_live:
            text, prompt_toks, out_toks = await self._infer_llama_server(req)
            backend_label = "llama.cpp"
        else:
            text, prompt_toks, out_toks = self._infer_mock(req)
            backend_label = "mock_edge_engine"

        latency_ms = (time.time() - start_time) * 1000.0

        # Energy consumption estimate:
        # If current_power_w is 0 (mock probe), use 9.557W (calibrated Orin Nano active power)
        active_power_w = current_power_w if current_power_w > 1.0 else 9.557
        duration_s = latency_ms / 1000.0
        energy_j = active_power_w * duration_s

        logger.info(
            "Inference [%s] backend=%s prompt_tokens=%d out_tokens=%d latency=%.1fms energy=%.2fJ",
            req.request_id,
            backend_label,
            prompt_toks,
            out_toks,
            latency_ms,
            energy_j,
        )

        return InferenceResponse(
            request_id=req.request_id,
            node_id=self.config.node_id,
            text=text,
            prompt_tokens=prompt_toks,
            output_tokens=out_toks,
            latency_ms=round(latency_ms, 2),
            energy_consumed_j_est=round(energy_j, 3),
        )

    async def _infer_llama_server(self, req: InferenceRequest) -> tuple[str, int, int]:
        """Proxy prompt to llama.cpp /completion endpoint."""
        payload = {
            "prompt": req.prompt,
            "n_predict": req.max_output_tokens,
            "stream": False,
        }
        res = await self.http_client.post(
            f"{self.config.llama_cpp_url}/completion",
            json=payload,
        )
        res.raise_for_status()
        data = res.json()
        text = data.get("content", "").strip()
        tokens_evaluated = data.get("tokens_evaluated", req.prompt_tokens_est)
        tokens_predicted = data.get("tokens_predicted", len(text.split()))
        return text, tokens_evaluated, tokens_predicted

    def _infer_mock(self, req: InferenceRequest) -> tuple[str, int, int]:
        """Calibrated mock generation when llama.cpp server is offline."""
        mock_text = (
            f"[SunRoute {self.config.node_id}] Processed '{req.task_type.value}' query "
            f"for origin site {req.origin.site} ({req.origin.city}). "
            "Edge inference served locally under community energy policy."
        )
        words = mock_text.split()
        out_tokens = min(len(words), req.max_output_tokens)
        return mock_text, req.prompt_tokens_est, out_tokens
