"""Pydantic data models and schemas for SunRoute Edge Agent and Router.

Matches CLAUDE.md Section 6 specifications.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskType(str, Enum):
    CLASSIFY = "classify"
    SHORT_QA = "short_qa"
    SUMMARIZE = "summarize"
    CHAT = "chat"
    LONG_FORM = "long_form"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    ESSENTIAL = "essential"


class Privacy(str, Enum):
    LOCAL_ONLY = "local_only"
    LOCAL_PREFERRED = "local_preferred"
    ANY = "any"


class QualityTier(str, Enum):
    BASIC = "basic"
    STANDARD = "standard"
    HIGH = "high"


class NodeKind(str, Enum):
    PHYSICAL = "physical"
    EMULATED = "emulated"
    CLOUD = "cloud"


class ConnectivityStatus(str, Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class EnergySource(str, Enum):
    SIMULATED = "simulated"
    MEASURED = "measured"


class Origin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str = Field(..., description="Origin city ID, e.g. 'city-01'")
    site: str = Field(..., description="Origin site or community ID, e.g. 'society-12'")


class InferenceRequest(BaseModel):
    """Client request schema per CLAUDE.md Section 6.1."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID = Field(..., description="Unique request identifier")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="ISO-8601 creation timestamp",
    )
    origin: Origin = Field(..., description="Geographical origin of the request")
    task_type: TaskType = Field(..., description="Category of inference task")
    prompt_tokens_est: int = Field(
        ...,
        ge=1,
        le=2048,
        description="Estimated token length of the prompt (1-2048)",
    )
    max_output_tokens: int = Field(
        ...,
        ge=1,
        le=1024,
        description="Maximum generation tokens requested (1-1024)",
    )
    latency_target_ms: int = Field(
        ...,
        ge=50,
        le=60000,
        description="Target latency budget in milliseconds",
    )
    priority: Priority = Field(
        default=Priority.NORMAL,
        description="Request priority class",
    )
    privacy: Privacy = Field(
        default=Privacy.ANY,
        description="Privacy constraint for data locality",
    )
    min_quality_tier: QualityTier = Field(
        default=QualityTier.BASIC,
        description="Minimum acceptable model quality tier",
    )
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=8192,
        description="Inference prompt text (max 8192 chars)",
    )
    image_data_url: str | None = Field(
        default=None,
        description="Optional base64 image data URL for multimodal vision tasks",
    )


class InferenceResponse(BaseModel):
    """Response returned after edge or cloud model inference."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID = Field(..., description="Original request ID")
    node_id: str = Field(..., description="Executing node ID")
    text: str = Field(..., description="Generated completion text")
    prompt_tokens: int = Field(..., ge=0, description="Tokens evaluated in prompt")
    output_tokens: int = Field(..., ge=0, description="Tokens generated")
    latency_ms: float = Field(..., ge=0.0, description="End-to-end execution latency in ms")
    energy_consumed_j_est: float = Field(
        ..., ge=0.0, description="Estimated inference energy consumed in Joules"
    )


class NodeState(BaseModel):
    """Telemetry and resource status schema per CLAUDE.md Section 6.2."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(..., description="Node identifier, e.g. 'jetson-01'")
    city: str = Field(..., description="Home city identifier, e.g. 'city-01'")
    kind: NodeKind = Field(..., description="Node infrastructure kind")
    ts: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of telemetry report",
    )
    models: list[str] = Field(default_factory=list, description="Available GGUF models on node")
    free_mem_mb: float = Field(..., ge=0.0, description="Available memory in MB")
    gpu_util: float = Field(..., ge=0.0, le=1.0, description="Current GPU utilization (0.0-1.0)")
    queue_depth: int = Field(..., ge=0, description="Current active + pending requests")
    temp_c: float = Field(..., description="Current SoC temperature in Celsius")
    battery_soc: float = Field(
        ..., ge=0.0, le=1.0, description="Current battery state of charge (0.0-1.0)"
    )
    solar_w: float = Field(default=0.0, ge=0.0, description="Current solar power in Watts")
    wind_w: float = Field(default=0.0, ge=0.0, description="Current wind power in Watts")
    load_w: float = Field(default=0.0, ge=0.0, description="Current system load power in Watts")
    connectivity: ConnectivityStatus = Field(
        default=ConnectivityStatus.ONLINE, description="Network connectivity status"
    )
    energy_source: EnergySource = Field(
        default=EnergySource.MEASURED, description="Simulated vs measured energy source"
    )


class HealthResponse(BaseModel):
    """Node health and readiness status."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., description="'healthy', 'degraded', or 'unhealthy'")
    node_id: str = Field(..., description="Node ID")
    runtime_backend: str = Field(..., description="Inference runtime name")
    uptime_s: float = Field(..., ge=0.0, description="Agent uptime in seconds")
    queue_depth: int = Field(..., ge=0, description="Current queue depth")
