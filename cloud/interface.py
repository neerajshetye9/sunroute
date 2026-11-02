"""Unified abstract interface for cloud inference clients.

Both AWS Bedrock/EC2 production client and MockCloudClient implement this interface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from edge.schemas import InferenceRequest, InferenceResponse, NodeState


@runtime_checkable
class CloudInferenceClient(Protocol):
    """Protocol for cloud inference execution and state monitoring."""

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Execute inference on the cloud model."""
        ...

    async def get_state(self) -> NodeState:
        """Return telemetry and health status of the cloud tier."""
        ...
