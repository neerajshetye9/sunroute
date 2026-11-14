"""FastAPI Edge Agent application for SunRoute.

Implements /infer, /state, and /health endpoints with Bearer token authentication,
pydantic validation, queue depth throttling, and deterministic safety limits.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from edge.config import EdgeConfig
from edge.runtime import EdgeRuntime
from edge.schemas import (
    ConnectivityStatus,
    EnergySource,
    HealthResponse,
    InferenceRequest,
    InferenceResponse,
    NodeKind,
    NodeState,
    Priority,
)
from scripts.jetson_power_probe import JetsonPowerProbe

logger = logging.getLogger("edge_agent")

security = HTTPBearer(auto_error=False)


class EdgeAppManager:
    """Manages application state, telemetry probe, and inference concurrency."""

    def __init__(self, config: EdgeConfig | None = None):
        self.config = config or EdgeConfig()
        self.runtime = EdgeRuntime(self.config)
        self.probe = JetsonPowerProbe()
        self.start_time = time.time()
        self.queue_depth = 0
        self.lock = asyncio.Lock()

        # Simulated state values (can be updated or calibrated)
        self.battery_soc = 0.85
        self.solar_w = 12.0
        self.wind_w = 2.0
        self.load_w = 7.5


def create_app(config: EdgeConfig | None = None) -> FastAPI:
    manager = EdgeAppManager(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("Starting SunRoute Edge Agent [%s]...", manager.config.node_id)
        yield
        await manager.runtime.close()
        logger.info("SunRoute Edge Agent shut down.")

    app = FastAPI(
        title="SunRoute Edge Agent",
        version="0.1.0",
        description="Edge node agent for community AI inference",
        lifespan=lifespan,
    )
    app.state.manager = manager

    async def verify_token(
        credentials: HTTPAuthorizationCredentials | None = Security(security),
    ) -> str:
        """Validate Bearer token for protected endpoints."""
        if not credentials or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Bearer authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if credentials.credentials != manager.config.api_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return credentials.credentials

    @app.post(
        "/infer",
        response_model=InferenceResponse,
        status_code=status.HTTP_200_OK,
        summary="Execute edge inference",
    )
    async def infer(
        request: InferenceRequest,
        _token: str = Depends(verify_token),
    ) -> InferenceResponse:
        # 1. Payload size limits
        if request.prompt_tokens_est > manager.config.max_prompt_tokens:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Prompt tokens ({request.prompt_tokens_est}) exceed "
                    f"maximum allowed ({manager.config.max_prompt_tokens})"
                ),
            )
        if len(request.prompt) > manager.config.max_prompt_chars:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Prompt character length ({len(request.prompt)}) exceeds "
                    f"maximum allowed ({manager.config.max_prompt_chars})"
                ),
            )

        # 2. Concurrency / Queue depth rate limiting
        async with manager.lock:
            if manager.queue_depth >= manager.config.max_queue_depth:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"Edge node queue full (depth={manager.queue_depth}, "
                        f"max={manager.config.max_queue_depth})"
                    ),
                )
            manager.queue_depth += 1

        try:
            # 3. Read current power and check thermal / critical SOC limits
            reading = manager.probe.read_sample()

            if (
                reading.temp_c_measured > manager.config.thermal_limit_c
                and reading.temp_c_measured > 0
            ):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        f"Node thermal limit exceeded "
                        f"({reading.temp_c_measured:.1f}°C > {manager.config.thermal_limit_c}°C)"
                    ),
                )

            if (
                manager.battery_soc < manager.config.critical_battery_soc
                and request.priority != Priority.ESSENTIAL
            ):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        f"Battery critically low ({manager.battery_soc * 100:.1f}%). "
                        "Only essential requests accepted."
                    ),
                )

            # 4. Execute inference
            response = await manager.runtime.infer(request, reading.power_w_measured)
            return response
        finally:
            async with manager.lock:
                manager.queue_depth = max(0, manager.queue_depth - 1)

    @app.get(
        "/state",
        response_model=NodeState,
        status_code=status.HTTP_200_OK,
        summary="Get live node state and telemetry",
    )
    async def get_state() -> NodeState:
        reading = manager.probe.read_sample()
        is_measured = reading.source != "mock_host"

        return NodeState(
            node_id=manager.config.node_id,
            city=manager.config.city,
            kind=NodeKind(manager.config.kind),
            models=manager.config.models,
            free_mem_mb=reading.ram_total_mb_measured - reading.ram_used_mb_measured,
            gpu_util=reading.gpu_util_measured,
            queue_depth=manager.queue_depth,
            temp_c=reading.temp_c_measured,
            battery_soc=manager.battery_soc,
            solar_w=manager.solar_w,
            wind_w=manager.wind_w,
            load_w=reading.power_w_measured if reading.power_w_measured > 0 else manager.load_w,
            connectivity=ConnectivityStatus.ONLINE,
            energy_source=EnergySource.MEASURED if is_measured else EnergySource.SIMULATED,
        )

    @app.get(
        "/health",
        response_model=HealthResponse,
        status_code=status.HTTP_200_OK,
        summary="Node health check",
    )
    @app.get(
        "/v1/health",
        response_model=HealthResponse,
        status_code=status.HTTP_200_OK,
        summary="Node health check (v1)",
    )
    async def get_health() -> HealthResponse:
        uptime = time.time() - manager.start_time
        is_alive = await manager.runtime.is_llama_server_alive()
        runtime_name = "llama.cpp" if is_alive else "mock_edge_engine"
        node_status = (
            "healthy" if manager.queue_depth < manager.config.max_queue_depth else "degraded"
        )

        return HealthResponse(
            status=node_status,
            node_id=manager.config.node_id,
            runtime_backend=runtime_name,
            uptime_s=round(uptime, 2),
            queue_depth=manager.queue_depth,
        )

    return app


# Default app instance
app = create_app()
