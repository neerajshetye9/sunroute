"""Mock cloud inference client simulating AWS Bedrock / EC2 heavy model execution.

Exposes the exact same interface as the production AWS Bedrock client with
high-fidelity simulated datacenter latency, energy profiles, and rich reasoning.
All energy metrics are strictly labelled '_estimated' per Section 3.
"""

from __future__ import annotations

import asyncio
import re

from edge.schemas import (
    ConnectivityStatus,
    EnergySource,
    InferenceRequest,
    InferenceResponse,
    NodeKind,
    NodeState,
)


def generate_cloud_knowledge_response(prompt: str, task_type: str = "chat") -> str:
    """Generate high-quality intelligent response for cloud data center fallback."""
    p_lower = prompt.lower()

    if any(k in p_lower for k in ["microgrid", "solar", "battery"]):
        return (
            "Solar-battery microgrids integrate localized photovoltaic arrays, battery energy\n"
            "storage systems (BESS), and intelligent energy management controllers to deliver\n"
            "autonomous, clean power. During peak daylight, excess solar generation charges\n"
            "battery banks and powers local computing workloads. When irradiance drops, stored\n"
            "battery capacity maintains continuous operation without drawing from carbon-heavy\n"
            "fossil grids. In SunRoute, microgrid nodes coordinate dynamically to execute\n"
            "distributed AI inference with near-zero emissions."
        )

    if any(k in p_lower for k in ["electricity", "power", "grid", "energy"]):
        return (
            "Electricity in renewable microgrids flows through decentralized distribution\n"
            "networks powered by photovoltaic cells and wind turbines. Smart inverters convert\n"
            "direct current (DC) into alternating current (AC) while dynamic load balancing\n"
            "schedules high-demand compute tasks during peak generation windows. This preserves\n"
            "battery state-of-charge (SOC) and ensures resilience against utility outages."
        )

    if any(k in p_lower for k in ["latency", "rtt", "routing", "network"]):
        return (
            "SunRoute's spatial routing algorithm optimizes end-to-end latency by evaluating\n"
            "geographic distance across Maharashtra's 30-city optical network, local compute\n"
            "queue depths, and current battery SOC. Queries originating at community sites are\n"
            "resolved at the closest available renewable edge node (sub-10ms RTT) before\n"
            "escalating to regional hubs or central AWS Bedrock data centers."
        )

    if any(k in p_lower for k in ["jetson", "orin", "gpu", "hardware"]):
        return (
            "The NVIDIA Jetson Orin Nano Super 8GB features an Ampere architecture GPU with\n"
            "1024 CUDA cores and 32 Tensor Cores, delivering up to 40 TOPS of AI compute.\n"
            "At a measured active power draw of 9.557 W and an idle baseline of 4.987 W, it\n"
            "achieves 28.1 tokens/second generation speed at just 0.339 Joules per token,\n"
            "making it ideal for solar-powered edge AI."
        )

    if any(k in p_lower for k in ["aws", "bedrock", "datacenter", "cloud"]):
        return (
            "AWS Bedrock provides serverless access to foundation models such as Anthropic\n"
            "Claude 3 and Amazon Titan hosted in hyperscale data centers. While cloud data\n"
            "centers offer virtually unconstrained compute for complex reasoning, they consume\n"
            "an estimated ~250 W per GPU blade (7.2 J/token) and introduce WAN latency (65ms+),\n"
            "making local edge routing preferable for sustainable, fast interactions."
        )

    # General conversational response
    clean_p = re.sub(r"<\|im_start\|>.*?<\|im_end\|>", "", prompt, flags=re.DOTALL).strip()
    clean_p = clean_p.replace("user\n", "").replace("system\n", "").strip()

    return (
        f"Processed query on AWS Bedrock Central Data Center tier: '{clean_p}'.\n"
        "The central cloud cluster provides high-capacity model reasoning across\n"
        "distributed regional requests. Dynamic microgrid routing routes compute-heavy\n"
        "queries here when edge batteries are conserving energy."
    )


class MockCloudClient:
    """Simulates AWS Bedrock/EC2 inference with data-center latency and energy profiles."""

    def __init__(
        self,
        node_id: str = "aws-bedrock-central",
        city: str = "city-01",  # Mumbai capital data center
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
        """Simulate data center inference execution with realistic latency and high quality text."""
        out_tokens = min(request.max_output_tokens, 95)
        compute_time_s = out_tokens / self.tokens_per_sec
        total_latency_ms = self.simulated_rtt_ms + (compute_time_s * 1000.0)

        # Sleep asynchronously for simulated WAN latency (capped for fast testing)
        sleep_s = min(0.04, total_latency_ms / 1000.0)
        await asyncio.sleep(sleep_s)

        # Datacenter estimated energy: ~7.2 J/token (0.002 Wh/token datacenter baseline)
        energy_j = (request.prompt_tokens_est + out_tokens) * 7.2

        body_text = generate_cloud_knowledge_response(request.prompt, request.task_type.value)
        completion_text = f"[AWS Bedrock Central - Cloud Data Center]\n\n{body_text}"

        return InferenceResponse(
            request_id=request.request_id,
            node_id=self.node_id,
            text=completion_text,
            prompt_tokens=request.prompt_tokens_est,
            output_tokens=out_tokens,
            latency_ms=round(total_latency_ms, 2),
            energy_consumed_j_est=round(energy_j, 2),
        )

    async def get_state(self) -> NodeState:
        """Return simulated cloud data center telemetry state."""
        return NodeState(
            node_id=self.node_id,
            city=self.city,
            kind=NodeKind.CLOUD,
            models=["anthropic.claude-3-haiku-v1", "amazon.titan-text-express-v1"],
            free_mem_mb=128000,
            gpu_util=0.35,
            queue_depth=2,
            temp_c=38.5,
            battery_soc=1.0,  # Grid powered
            solar_w=0.0,
            wind_w=0.0,
            load_w=self.gpu_power_w_est,
            connectivity=ConnectivityStatus.ONLINE,
            energy_source=EnergySource.SIMULATED,
        )
