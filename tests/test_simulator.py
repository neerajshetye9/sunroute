"""Unit tests for SunRoute Phase 3 Simulators.

Verifies:
- Solar generation with pvlib and diurnal curves
- Wind turbine Weibull model and power curve
- Battery SOC integration and conservation of energy
- 30-city state topology and hierarchical latency matrix
- Seeded reproducible workload generation
- SimPy discrete-event simulation engine across policies
- Experiment runner and Section 7 summary metrics
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from experiments.runner import ExperimentRunner
from router.schemas import PolicyType
from simulator.energy import (
    BatteryConfig,
    BatteryModel,
    NodeEnergySimulator,
    SolarConfig,
    SolarModel,
    WindConfig,
    WindModel,
)
from simulator.sim_engine import SimulationEngine
from simulator.topology import StateTopology, TopologyConfig
from simulator.workload import WorkloadConfig, WorkloadGenerator


def test_solar_model_diurnal_and_factors() -> None:
    solar = SolarModel(config=SolarConfig(), seed=42)

    # Midday in June (approx 12:00 local time)
    midday = datetime(2026, 6, 21, 6, 30, tzinfo=UTC)  # 12:00 IST is 06:30 UTC
    p_clear = solar.power_w(midday, solar_factor=1.0)
    assert p_clear > 15.0  # Significant solar output

    # Cloudy scenario
    p_cloudy = solar.power_w(midday, solar_factor=0.2)
    assert 0.0 < p_cloudy < p_clear
    assert pytest.approx(p_cloudy / p_clear, rel=0.05) == 0.2

    # Night scenario
    p_night = solar.power_w(midday, solar_factor=0.0)
    assert p_night == 0.0


def test_wind_model_weibull_and_bounds() -> None:
    cfg = WindConfig(rated_power_w=20.0)
    wind = WindModel(config=cfg, seed=42)

    # Power is 0 when wind_factor is 0
    assert wind.power_w(100.0, wind_factor=0.0) == 0.0

    # Power is bounded by rated power * wind_factor
    powers = [wind.power_w(float(t), wind_factor=1.0) for t in range(0, 3600, 300)]
    for p in powers:
        assert 0.0 <= p <= cfg.rated_power_w

    # Determinism: same seed produces identical sequence
    wind2 = WindModel(config=cfg, seed=42)
    powers2 = [wind2.power_w(float(t), wind_factor=1.0) for t in range(0, 3600, 300)]
    assert powers == powers2


def test_battery_model_soc_dynamics() -> None:
    cfg = BatteryConfig(
        capacity_wh=50.0,
        initial_soc=0.50,
        reserve_soc=0.20,
        critical_soc=0.10,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
    )
    battery = BatteryModel(config=cfg)

    # Charging: +50W for 0.5 hours = +25Wh -> SOC should increase by 25/50 = 0.50 -> 1.00
    soc, is_reserve = battery.update(net_power_w=50.0, dt_seconds=1800.0)
    assert pytest.approx(soc, abs=1e-3) == 1.0
    assert not is_reserve

    # Overcharge clamping
    soc, _ = battery.update(net_power_w=20.0, dt_seconds=600.0)
    assert soc == 1.0

    # Discharging: -40W for 1.0 hour = -40Wh -> SOC should drop by 40/50 = 0.80 -> 0.20
    soc, is_reserve = battery.update(net_power_w=-40.0, dt_seconds=3600.0)
    assert pytest.approx(soc, abs=1e-3) == 0.20
    assert is_reserve

    # Critical drop
    soc, _ = battery.update(net_power_w=-10.0, dt_seconds=3600.0)
    assert soc < 0.10
    assert battery.floor_violations > 0


def test_node_energy_simulator_telemetry_labels() -> None:
    sim = NodeEnergySimulator(
        node_id="node-test-1",
        city="city-01",
        idle_power_w=3.5,
        active_power_w=10.5,
        seed=42,
    )
    t = datetime(2026, 6, 21, 6, 30, tzinfo=UTC)
    telemetry = sim.step(
        sim_timestamp=t,
        sim_second=100.0,
        dt_seconds=5.0,
        is_inferring=True,
        solar_factor=1.0,
        wind_factor=0.5,
    )

    # Every metric must be labelled _simulated per Section 3
    assert "solar_w_simulated" in telemetry
    assert "wind_w_simulated" in telemetry
    assert "generation_w_simulated" in telemetry
    assert "load_w_simulated" in telemetry
    assert "battery_soc_simulated" in telemetry
    assert telemetry["load_w_simulated"] == 10.5
    assert telemetry["energy_source"] == "simulated"


def test_state_topology_30_cities_hierarchy() -> None:
    topo = StateTopology(TopologyConfig(num_cities=30, nodes_per_city=3), seed=42)
    assert len(topo.cities) == 30
    assert len(topo.node_to_city) == 90

    # Intra-city latency
    intra_rtt = topo.calculate_rtt_ms("city-01", "city-01")
    assert intra_rtt == topo.config.base_intra_city_rtt_ms

    # Regional neighbor vs remote city
    reg_c2 = topo.region_to_cities["region-central"][1]
    remote_c = topo.region_to_cities["region-north"][0]

    intra_reg_rtt = topo.calculate_rtt_ms("city-01", reg_c2)
    cross_reg_rtt = topo.calculate_rtt_ms("city-01", remote_c)
    assert intra_rtt < intra_reg_rtt < cross_reg_rtt

    # Hierarchy level classification
    target_node_local = topo.city_to_nodes["city-01"][0]
    target_node_reg = topo.city_to_nodes[reg_c2][0]
    assert topo.get_hierarchy_level("city-01", target_node_local) == "local"
    assert topo.get_hierarchy_level("city-01", target_node_reg) == "region"


def test_workload_generator_determinism() -> None:
    cities = ["city-01", "city-02", "city-03"]
    gen1 = WorkloadGenerator(cities=cities, config=WorkloadConfig(total_requests=25, seed=123))
    gen2 = WorkloadGenerator(cities=cities, config=WorkloadConfig(total_requests=25, seed=123))

    trace1 = gen1.generate_trace()
    trace2 = gen2.generate_trace()

    assert len(trace1) == len(trace2)
    for (t1, r1), (t2, r2) in zip(trace1, trace2, strict=True):
        assert t1 == t2
        assert r1.origin.city == r2.origin.city
        assert r1.task_type == r2.task_type
        assert r1.priority == r2.priority


def test_simulation_engine_run() -> None:
    scenario_params = {
        "solar_factor": 1.0,
        "wind_factor": 0.5,
        "initial_soc": 0.85,
        "duration_hours": 0.5,
    }
    engine = SimulationEngine(
        scenario_name="test_sunny",
        scenario_params=scenario_params,
        policy=PolicyType.PROPOSED,
        seed=42,
    )

    cities = [f"city-{i:02d}" for i in range(1, 31)]
    gen = WorkloadGenerator(cities=cities, config=WorkloadConfig(total_requests=10, seed=42))
    trace = gen.generate_trace()

    records = engine.run(trace)
    assert len(records) > 0
    for r in records:
        assert r.scenario == "test_sunny"
        assert r.policy == "proposed"
        assert r.latency_ms_simulated >= 0.0
        assert 0.0 <= r.renewable_share_simulated <= 1.0


def test_experiment_runner_matrix_and_summary(tmp_path: Path) -> None:
    runner = ExperimentRunner(
        output_dir=tmp_path / "results",
        duckdb_path=tmp_path / "test.duckdb",
    )
    # Fast test duration
    runner.scenarios["sunny_day"]["duration_hours"] = 0.5

    df = runner.run_matrix(
        scenarios=["sunny_day"],
        policies=["proposed", "cloud_only"],
        repeats=1,
        num_requests=15,
    )
    assert not df.empty
    assert "latency_ms_simulated" in df.columns
    assert "edge_energy_j_simulated" in df.columns

    summary = ExperimentRunner.compute_summary_metrics(df)
    assert len(summary) == 2  # 2 policies
    assert "community_share_simulated" in summary.columns
    assert "gini_fairness_simulated" in summary.columns

    # Cloud only policy should have 0% community edge share
    cloud_summary = summary[summary["policy"] == "cloud_only"].iloc[0]
    assert cloud_summary["community_share_simulated"] == 0.0
    assert cloud_summary["cloud_request_count"] > 0

    # Proposed policy should answer queries on community nodes
    prop_summary = summary[summary["policy"] == "proposed"].iloc[0]
    assert prop_summary["community_share_simulated"] > 0.0
