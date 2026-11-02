"""Unit tests for deterministic energy rules and admission control."""

import uuid

from edge.energy_rules import (
    calculate_projected_soc,
    estimate_job_energy,
    evaluate_admission,
)
from edge.schemas import (
    ConnectivityStatus,
    EnergySource,
    InferenceRequest,
    NodeKind,
    NodeState,
    Origin,
    Priority,
    Privacy,
    QualityTier,
    TaskType,
)


def make_request(
    priority: Priority = Priority.NORMAL,
    prompt_tokens: int = 100,
    max_tokens: int = 100,
):
    return InferenceRequest(
        request_id=uuid.uuid4(),
        origin=Origin(city="city-01", site="society-12"),
        task_type=TaskType.SHORT_QA,
        prompt_tokens_est=prompt_tokens,
        max_output_tokens=max_tokens,
        latency_target_ms=2000,
        priority=priority,
        privacy=Privacy.ANY,
        min_quality_tier=QualityTier.BASIC,
        prompt="Test prompt",
    )


def make_node_state(
    soc: float = 0.80,
    temp_c: float = 50.0,
    solar_w: float = 10.0,
    wind_w: float = 0.0,
    load_w: float = 8.0,
):
    return NodeState(
        node_id="jetson-01",
        city="city-01",
        kind=NodeKind.PHYSICAL,
        models=["test-model"],
        free_mem_mb=4000.0,
        gpu_util=0.3,
        queue_depth=1,
        temp_c=temp_c,
        battery_soc=soc,
        solar_w=solar_w,
        wind_w=wind_w,
        load_w=load_w,
        connectivity=ConnectivityStatus.ONLINE,
        energy_source=EnergySource.MEASURED,
    )


def test_thermal_limit_rejection():
    req = make_request()
    state = make_node_state(temp_c=82.5)  # Exceeds 80C
    decision = evaluate_admission(req, state)
    assert not decision.admitted
    assert "Thermal limit exceeded" in decision.reason


def test_critical_battery_soc_rejection():
    req = make_request(priority=Priority.NORMAL)
    state = make_node_state(soc=0.08)  # Below 10% critical threshold
    decision = evaluate_admission(req, state)
    assert not decision.admitted
    assert "Battery critically low" in decision.reason


def test_reserve_floor_rejection_without_surplus():
    req = make_request(priority=Priority.NORMAL)
    # SOC at 18% (below 20% reserve floor), generation 5W < load 8W (no surplus)
    state = make_node_state(soc=0.18, solar_w=5.0, load_w=8.0)
    decision = evaluate_admission(req, state)
    assert not decision.admitted
    assert "reserve floor" in decision.reason.lower()


def test_reserve_floor_acceptance_with_surplus_generation():
    req = make_request(priority=Priority.NORMAL)
    # SOC at 18%, but solar 15W > load 8W + 2W threshold (active surplus)
    state = make_node_state(soc=0.18, solar_w=15.0, load_w=8.0)
    decision = evaluate_admission(req, state)
    assert decision.admitted
    assert decision.surplus_active
    assert "surplus" in decision.reason.lower()


def test_reserve_floor_acceptance_for_essential_task():
    req = make_request(priority=Priority.ESSENTIAL)
    # SOC at 18%, no surplus, but priority is ESSENTIAL
    state = make_node_state(soc=0.18, solar_w=2.0, load_w=8.0)
    decision = evaluate_admission(req, state)
    assert decision.admitted
    assert not decision.surplus_active


def test_healthy_operational_admission():
    req = make_request(priority=Priority.LOW)
    state = make_node_state(soc=0.75, temp_c=55.0)
    decision = evaluate_admission(req, state)
    assert decision.admitted
    assert decision.projected_soc < state.battery_soc
    assert decision.estimated_energy_j > 0.0


def test_projected_soc_calculation():
    # 200 tokens * 0.15 J/token = 30 J
    energy_j = estimate_job_energy(100, 100, 0.15)
    assert energy_j == 30.0

    # 50 Wh battery = 180,000 J
    # 30 J / 180,000 J = 0.0001666 delta
    initial_soc = 0.50
    proj_soc = calculate_projected_soc(initial_soc, energy_j, 50.0)
    assert proj_soc < initial_soc
    assert round(proj_soc, 4) == 0.4998
