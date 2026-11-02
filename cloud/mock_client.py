"""Mock cloud inference client simulating AWS Bedrock / EC2 heavy model execution.

Exposes the exact same interface as the production AWS client with simulated labels.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from edge.schemas import (
    ConnectivityStatus,
    EnergySource,
    InferenceRequest,
    InferenceResponse,
    NodeKind,
    NodeState,
)


class MockCloudClient:
    """Simulates AWS Bedrock/EC2 inference with data-center latency and energy profiles."""

    def __init__(
        self,
        node_id: str = "aws-bedrock-central",
        city: str = "capital-dc",
        simulated_rtt_ms: float = 65.0,
        tokens_per_sec: float = 75.0,
        gpu_power_w_est: float = 250.0,  # Estimated data center GPU allocation (W)
    ):
        self.node_id = node_id
        self.city = city
        self.simulated_rtt_ms = simulated_rtt_ms
        self.tokens_per_sec = tokens_per_sec
        self.gpu_power_w_est = gpu_power_w_est

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Simulate data center inference execution with realistic latency."""
        # Calculate simulated latency: network RTT + token generation
        out_tokens = min(64, request.max_output_tokens)
        compute_time_s = out_tokens / self.tokens_per_sec
        total_latency_ms = self.simulated_rtt_ms + (compute_time_s * 1000.0)

        # Sleep asynchronously for simulated RTT (capped during unit tests if needed)
        sleep_s = min(0.05, total_latency_ms / 1000.0)
        await asyncio.sleep(sleep_s)

        # Energy consumption estimate: power (W) * compute time (s)
        energy_j = self.gpu_power_w_est * compute_time_s

        completion_text = (
            f"[AWS Bedrock Central - Heavy Model] Processed '{request.task_type.value}' query "
            f"for {request.origin.city}/{request.origin.site}. "
            "Inference executed on central cloud data center tier."
        )

        return InferenceResponse(
            request_id=request.request_id,
            node_id=self.node_id,
            text=completion_text,
            prompt_tokens=request.prompt_tokens_est,
            output_tokens=out_tokens,
            latency_ms=round(total_latency_ms, 2),
            energy_consumed_j_est=round(energy_j, 3),
        )

    async def get_state(self) -> NodeState:
        """Return cloud tier state snapshot."""
        return NodeState(
            node_id=self.node_id,
            city=self.city,
            kind=NodeKind.CLOUD,
            models=["meta.llama3-70b-instruct-v1:0"],
            free_mem_mb=128000.0,  # Abundant cloud RAM
            gpu_util=0.45,
            queue_depth=0,
            temp_c=32.0,  # Climate-controlled data center
            battery_soc=1.0,  # Grid powered
            solar_w=0.0,
            wind_w=0.0,
            load_w=self.gpu_power_w_est,
            connectivity=ConnectivityStatus.ONLINE,
            energy_source=EnergySource.SIMULATED,
            ts=datetime.now(UTC),
        )
