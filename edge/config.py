"""Configuration loader for SunRoute Edge Agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class EdgeConfig:
    node_id: str = field(default_factory=lambda: os.getenv("EDGE_NODE_ID", "jetson-01"))
    city: str = field(default_factory=lambda: os.getenv("EDGE_CITY", "city-01"))
    site: str = field(default_factory=lambda: os.getenv("EDGE_SITE", "society-12"))
    kind: str = field(default_factory=lambda: os.getenv("EDGE_KIND", "physical"))
    api_token: str = field(default_factory=lambda: os.getenv("EDGE_API_TOKEN", "dev-edge-token"))

    # Server binding
    host: str = field(default_factory=lambda: os.getenv("EDGE_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("EDGE_PORT", "8001")))

    # Runtime backend (llama.cpp server)
    llama_cpp_url: str = field(
        default_factory=lambda: os.getenv("LLAMA_CPP_URL", "http://127.0.0.1:8080")
    )
    models: list[str] = field(
        default_factory=lambda: [
            os.getenv("EDGE_MODEL_NAME", "qwen2.5-1.5b-instruct-q4_k_m"),
        ]
    )

    # Size and rate limits
    max_queue_depth: int = field(default_factory=lambda: int(os.getenv("MAX_QUEUE_DEPTH", "10")))
    max_prompt_chars: int = field(
        default_factory=lambda: int(os.getenv("MAX_PROMPT_CHARS", "8192"))
    )
    max_prompt_tokens: int = field(
        default_factory=lambda: int(os.getenv("MAX_PROMPT_TOKENS", "2048"))
    )
    max_output_tokens: int = field(
        default_factory=lambda: int(os.getenv("MAX_OUTPUT_TOKENS", "1024"))
    )

    # Energy safety limits (from default.yaml)
    min_battery_soc: float = 0.20
    critical_battery_soc: float = 0.10
    thermal_limit_c: float = 80.0
