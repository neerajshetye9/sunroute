"""Workload trace generator for reproducible SunRoute simulation experiments.

Generates Poisson/bursty request arrivals across 30 cities with configurable
task types, priorities, privacy requirements, and scenario modifiers.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from edge.schemas import InferenceRequest, Origin, Priority, Privacy, QualityTier, TaskType


@dataclass
class WorkloadConfig:
    """Configuration for synthetic workload generation."""

    total_requests: int = 200
    duration_hours: float = 2.0
    seed: int = 42
    load_multiplier: float = 1.0
    spike_multiplier: float = 1.0
    spike_at_min: float = -1.0  # -1 means no spike
    spike_duration_min: float = 10.0


class WorkloadGenerator:
    """Generates deterministic, seeded traces of InferenceRequest instances."""

    def __init__(self, cities: list[str], config: WorkloadConfig | None = None) -> None:
        self.cities = cities or [f"city-{i:02d}" for i in range(1, 31)]
        self.config = config or WorkloadConfig()
        self.rng = random.Random(self.config.seed)

    def generate_trace(
        self,
        start_time: datetime | None = None,
        scenario_params: dict[str, Any] | None = None,
    ) -> list[tuple[float, InferenceRequest]]:
        """Generate a chronological list of (arrival_offset_seconds, request).

        arrival_offset_seconds: simulation elapsed seconds from start_time.
        """
        start = start_time or datetime(2026, 6, 21, 10, 0, tzinfo=UTC)
        params = scenario_params or {}

        load_mult = params.get("load_multiplier", self.config.load_multiplier)
        total_reqs = int(self.config.total_requests * load_mult)
        duration_s = params.get("duration_hours", self.config.duration_hours) * 3600.0
        mean_interarrival = duration_s / max(1, total_reqs)

        spike_mult = params.get("spike_multiplier", self.config.spike_multiplier)
        spike_start_s = params.get("spike_at_min", self.config.spike_at_min) * 60.0
        spike_end_s = spike_start_s + (
            params.get("spike_duration_min", self.config.spike_duration_min) * 60.0
        )

        trace: list[tuple[float, InferenceRequest]] = []
        current_s = 0.0

        task_types = [
            (TaskType.CLASSIFY, 0.35, 64, 32),
            (TaskType.SHORT_QA, 0.35, 128, 64),
            (TaskType.SUMMARIZE, 0.15, 512, 128),
            (TaskType.CHAT, 0.10, 256, 128),
            (TaskType.LONG_FORM, 0.05, 1024, 256),
        ]
        priorities = [
            (Priority.LOW, 0.15),
            (Priority.NORMAL, 0.65),
            (Priority.HIGH, 0.15),
            (Priority.ESSENTIAL, 0.05),
        ]
        privacies = [
            (Privacy.ANY, 0.70),
            (Privacy.LOCAL_PREFERRED, 0.20),
            (Privacy.LOCAL_ONLY, 0.10),
        ]

        while len(trace) < total_reqs and current_s < duration_s:
            # Check if within traffic spike window
            if spike_start_s <= current_s <= spike_end_s and spike_mult > 1.0:
                dt = self.rng.expovariate(spike_mult / mean_interarrival)
            else:
                dt = self.rng.expovariate(1.0 / mean_interarrival)

            current_s += dt
            if current_s > duration_s:
                break

            req_time = start + timedelta(seconds=current_s)
            city = self.rng.choice(self.cities)
            site = f"society-{self.rng.randint(1, 20):02d}"

            # Sample task
            r_task = self.rng.random()
            cum = 0.0
            task_type = TaskType.SHORT_QA
            p_tok = 120
            out_tok = 64
            for t_type, weight, p_len, o_len in task_types:
                cum += weight
                if r_task <= cum:
                    task_type = t_type
                    p_tok = p_len
                    out_tok = o_len
                    break

            # Sample priority
            r_prio = self.rng.random()
            cum = 0.0
            priority = Priority.NORMAL
            for prio, weight in priorities:
                cum += weight
                if r_prio <= cum:
                    priority = prio
                    break

            # Sample privacy
            r_priv = self.rng.random()
            cum = 0.0
            privacy = Privacy.ANY
            for priv, weight in privacies:
                cum += weight
                if r_priv <= cum:
                    privacy = priv
                    break

            # Create request
            req = InferenceRequest(
                request_id=uuid4(),
                created_at=req_time,
                origin=Origin(city=city, site=site),
                task_type=task_type,
                prompt_tokens_est=p_tok,
                max_output_tokens=out_tok,
                latency_target_ms=3000,
                priority=priority,
                privacy=privacy,
                min_quality_tier=QualityTier.BASIC,
                prompt=f"Simulated query for {task_type.value} from {city} {site}",
            )
            trace.append((round(current_s, 2), req))

        return trace
