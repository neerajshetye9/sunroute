"""SimPy-based discrete-event simulation engine for state-scale SunRoute evaluations.

Simulates 30 cities, hundreds of edge nodes, solar/wind variation, battery SOC,
network delay hierarchy, and dynamic routing across all 5 policies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import simpy

from edge.schemas import (
    ConnectivityStatus,
    EnergySource,
    InferenceRequest,
    NodeKind,
    NodeState,
)
from router.core import route
from router.ledger import FairnessLedger
from router.schemas import PolicyType, RouterConfig
from simulator.energy import BatteryConfig, NodeEnergySimulator, SolarConfig, WindConfig
from simulator.topology import StateTopology, TopologyConfig


@dataclass
class SimulationRecord:
    """Detailed record of an inference request simulation event."""

    request_id: str
    scenario: str
    policy: str
    sim_time_s: float
    timestamp_iso: str
    origin_city: str
    target_node_id: str | None
    target_level: str
    task_type: str
    priority: str
    privacy: str
    prompt_tokens: int
    output_tokens: int
    status: str  # 'completed', 'rejected', 'dropped'
    latency_ms_simulated: float
    network_rtt_ms_simulated: float
    execution_time_ms_simulated: float
    is_local_residency: bool
    is_outage_period: bool
    edge_energy_j_simulated: float
    cloud_energy_j_simulated: float
    battery_soc_simulated: float
    renewable_share_simulated: float
    reason: str


class SimulationEngine:
    """Discrete-event simulation engine using SimPy."""

    def __init__(
        self,
        scenario_name: str,
        scenario_params: dict[str, Any],
        policy: PolicyType,
        router_config: RouterConfig | None = None,
        topology_config: TopologyConfig | None = None,
        seed: int = 42,
    ) -> None:
        self.scenario_name = scenario_name
        self.scenario_params = scenario_params
        self.policy = policy
        self.router_config = router_config or RouterConfig()
        self.seed = seed
        self.start_time = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)

        self.env = simpy.Environment()
        self.topology = StateTopology(topology_config, seed=seed)
        self.ledger = FairnessLedger(min_service_floor=self.router_config.min_service_floor)

        # Node models
        self.energy_simulators: dict[str, NodeEnergySimulator] = {}
        self.node_states: dict[str, NodeState] = {}
        self.node_resources: dict[str, simpy.Resource] = {}
        self.offline_nodes: set[str] = set()

        # Cloud state
        self.cloud_state = NodeState(
            node_id="cloud-datacenter-01",
            city="city-01",
            kind=NodeKind.CLOUD,
            models=["mock-cloud-model"],
            free_mem_mb=128000,
            gpu_util=0.20,
            queue_depth=0,
            temp_c=40,
            battery_soc=1.0,
            solar_w=0.0,
            wind_w=0.0,
            load_w=250.0,
            connectivity=ConnectivityStatus.ONLINE,
            energy_source=EnergySource.SIMULATED,
        )

        self.internet_online: bool = True
        self.records: list[SimulationRecord] = []
        self._last_telemetry_sim_time: float = -1.0

        self._init_nodes()

    def _init_nodes(self) -> None:
        """Instantiate energy simulators, SimPy resources, and initial node states."""
        init_soc = float(self.scenario_params.get("initial_soc", 0.80))
        for city_id, node_list in self.topology.city_to_nodes.items():
            for n_id in node_list:
                b_cfg = BatteryConfig(initial_soc=init_soc)
                s_cfg = SolarConfig()
                w_cfg = WindConfig()
                sim = NodeEnergySimulator(
                    node_id=n_id,
                    city=city_id,
                    solar_config=s_cfg,
                    wind_config=w_cfg,
                    battery_config=b_cfg,
                    idle_power_w=3.5,
                    active_power_w=10.5,
                    seed=self.seed + hash(n_id) % 10000,
                )
                self.energy_simulators[n_id] = sim
                self.node_resources[n_id] = simpy.Resource(self.env, capacity=1)

                self.node_states[n_id] = NodeState(
                    node_id=n_id,
                    city=city_id,
                    kind=NodeKind.EMULATED,
                    models=["llama-3.2-1b-instruct-q4_k_m.gguf"],
                    free_mem_mb=4200,
                    gpu_util=0.0,
                    queue_depth=0,
                    temp_c=48,
                    battery_soc=init_soc,
                    solar_w=0.0,
                    wind_w=0.0,
                    load_w=3.5,
                    connectivity=ConnectivityStatus.ONLINE,
                    energy_source=EnergySource.SIMULATED,
                )

    def _update_telemetry(self, sim_second: float, dt_seconds: float = 5.0) -> None:
        """Update node telemetry from energy models and current queues."""
        curr_time = self.start_time + timedelta(seconds=sim_second)
        s_factor = float(self.scenario_params.get("solar_factor", 1.0))
        w_factor = float(self.scenario_params.get("wind_factor", 0.5))

        for n_id, sim in self.energy_simulators.items():
            res = self.node_resources[n_id]
            is_busy = res.count > 0
            energy_telemetry = sim.step(
                sim_timestamp=curr_time,
                sim_second=sim_second,
                dt_seconds=dt_seconds,
                is_inferring=is_busy,
                solar_factor=s_factor,
                wind_factor=w_factor,
            )

            is_offline = n_id in self.offline_nodes
            conn = (
                ConnectivityStatus.OFFLINE
                if is_offline
                else (
                    ConnectivityStatus.DEGRADED
                    if not self.internet_online
                    else ConnectivityStatus.ONLINE
                )
            )

            state = self.node_states[n_id]
            state.solar_w = energy_telemetry["solar_w_simulated"]
            state.wind_w = energy_telemetry["wind_w_simulated"]
            state.load_w = energy_telemetry["load_w_simulated"]
            state.battery_soc = energy_telemetry["battery_soc_simulated"]
            state.queue_depth = len(res.queue) + res.count
            state.gpu_util = 0.85 if is_busy else 0.05
            state.temp_c = 65 if is_busy else 48
            state.connectivity = conn
            state.ts = curr_time

    def _ensure_telemetry_updated(self, sim_second: float) -> None:
        """Lazily update node telemetry if at least 5s has elapsed since last update."""
        dt = sim_second - self._last_telemetry_sim_time
        if dt < 5.0 and self._last_telemetry_sim_time >= 0.0:
            return
        self._update_telemetry(sim_second, dt_seconds=max(5.0, dt))
        self._last_telemetry_sim_time = sim_second

    def _scenario_disturbances_process(self) -> Any:
        """Inject scenario events: outages, node failures, city blackouts."""
        # Internet outage scenario
        if "outage_at_min_" in str(self.scenario_params.get("internet", "")):
            # format: outage_at_min_60_for_30
            yield self.env.timeout(60 * 60)
            self.internet_online = False
            yield self.env.timeout(30 * 60)
            self.internet_online = True

        # Node failure scenario
        fail_min = self.scenario_params.get("node_failure_at_min")
        if fail_min is not None:
            yield self.env.timeout(float(fail_min) * 60)
            # Fail node-city-01-1
            target_failed = "node-city-01-1"
            self.offline_nodes.add(target_failed)

        # City blackout scenario
        blackout_city = self.scenario_params.get("city_blackout")
        blackout_min = self.scenario_params.get("blackout_at_min")
        if blackout_city and blackout_min:
            yield self.env.timeout(float(blackout_min) * 60)
            for n_id in self.topology.city_to_nodes.get(blackout_city, []):
                self.offline_nodes.add(n_id)

    def _handle_request(self, req: InferenceRequest) -> Any:
        """Simulate routing, network transit, queuing, and execution for one request."""
        curr_sim_time = self.env.now
        self._ensure_telemetry_updated(curr_sim_time)
        now_dt = self.start_time + timedelta(seconds=curr_sim_time)
        now_ts = now_dt.timestamp()

        # Check internet outage affecting cross-city or cloud communication
        is_outage = not self.internet_online

        # Get candidate node states
        current_node_states = list(self.node_states.values())

        # If internet is down, remote and cloud nodes appear OFFLINE to local ingress
        if is_outage:
            visible_states: list[NodeState] = []
            for ns in current_node_states:
                if ns.city == req.origin.city:
                    visible_states.append(ns)
                else:
                    degraded = ns.model_copy()
                    degraded.connectivity = ConnectivityStatus.OFFLINE
                    visible_states.append(degraded)
            decision = route(
                request=req,
                node_states=visible_states,
                cloud_state=None,  # Cloud unreachable
                policy=self.policy,
                config=self.router_config,
                now=now_ts,
                random_seed=self.seed + int(curr_sim_time),
                ledger=self.ledger,
            )
        else:
            decision = route(
                request=req,
                node_states=current_node_states,
                cloud_state=self.cloud_state,
                policy=self.policy,
                config=self.router_config,
                now=now_ts,
                random_seed=self.seed + int(curr_sim_time),
                ledger=self.ledger,
            )

        # If rejected / no target eligible
        if not decision.target_node_id:
            rec = SimulationRecord(
                request_id=str(req.request_id),
                scenario=self.scenario_name,
                policy=self.policy.value,
                sim_time_s=round(curr_sim_time, 2),
                timestamp_iso=now_dt.isoformat(),
                origin_city=req.origin.city,
                target_node_id=None,
                target_level=decision.target_level.value,
                task_type=req.task_type.value,
                priority=req.priority.value,
                privacy=req.privacy.value,
                prompt_tokens=req.prompt_tokens_est,
                output_tokens=req.max_output_tokens,
                status="rejected",
                latency_ms_simulated=0.0,
                network_rtt_ms_simulated=0.0,
                execution_time_ms_simulated=0.0,
                is_local_residency=False,
                is_outage_period=is_outage,
                edge_energy_j_simulated=0.0,
                cloud_energy_j_simulated=0.0,
                battery_soc_simulated=0.0,
                renewable_share_simulated=0.0,
                reason=decision.reason,
            )
            self.records.append(rec)
            return

        target_id = decision.target_node_id
        is_cloud = decision.target_kind == NodeKind.CLOUD

        # Network transmission delay
        rtt_ms = self.topology.get_latency_to_node_ms(req.origin.city, target_id)
        # One-way network latency to server
        yield self.env.timeout((rtt_ms / 2.0) / 1000.0)

        if is_cloud:
            # Cloud execution: TTFT ~120ms, 80 tokens/sec
            cloud_exec_ms = 120.0 + (req.max_output_tokens / 80.0) * 1000.0
            yield self.env.timeout(cloud_exec_ms / 1000.0)
            # Return network flight
            yield self.env.timeout((rtt_ms / 2.0) / 1000.0)

            total_lat = rtt_ms + cloud_exec_ms
            # Cloud estimated energy: ~7.2 J per token (0.002 Wh/token datacenter estimate)
            cloud_j = (req.prompt_tokens_est + req.max_output_tokens) * 7.2

            rec = SimulationRecord(
                request_id=str(req.request_id),
                scenario=self.scenario_name,
                policy=self.policy.value,
                sim_time_s=round(curr_sim_time, 2),
                timestamp_iso=now_dt.isoformat(),
                origin_city=req.origin.city,
                target_node_id=target_id,
                target_level=decision.target_level.value,
                task_type=req.task_type.value,
                priority=req.priority.value,
                privacy=req.privacy.value,
                prompt_tokens=req.prompt_tokens_est,
                output_tokens=req.max_output_tokens,
                status="completed",
                latency_ms_simulated=round(total_lat, 2),
                network_rtt_ms_simulated=round(rtt_ms, 2),
                execution_time_ms_simulated=round(cloud_exec_ms, 2),
                is_local_residency=False,
                is_outage_period=is_outage,
                edge_energy_j_simulated=0.0,
                cloud_energy_j_simulated=round(cloud_j, 2),
                battery_soc_simulated=1.0,
                renewable_share_simulated=0.0,
                reason=decision.reason,
            )
            self.records.append(rec)
            return

        # Target is an edge node
        res = self.node_resources[target_id]
        t_enter_queue = self.env.now

        with res.request() as resource_req:
            yield resource_req
            queue_wait_ms = (self.env.now - t_enter_queue) * 1000.0

            # Edge execution calibrated from Jetson Orin Nano Super:
            # TTFT ~42.1ms, 28.13 tokens/s generation, 0.339 J/token measured
            exec_time_ms = 42.1 + (req.max_output_tokens / 28.13) * 1000.0
            yield self.env.timeout(exec_time_ms / 1000.0)

            # Return flight
            yield self.env.timeout((rtt_ms / 2.0) / 1000.0)

            total_lat = rtt_ms + queue_wait_ms + exec_time_ms
            edge_j = (req.prompt_tokens_est + req.max_output_tokens) * 0.339

            node_st = self.node_states[target_id]
            is_local = self.topology.node_to_city.get(target_id) == req.origin.city

            # Update ledger
            self.ledger.record_served(
                target_id, tokens=req.prompt_tokens_est + req.max_output_tokens
            )

            # Renewable share: fraction of current load covered by solar + wind
            tot_gen = node_st.solar_w + node_st.wind_w
            renew_share = min(1.0, tot_gen / max(0.1, node_st.load_w))

            rec = SimulationRecord(
                request_id=str(req.request_id),
                scenario=self.scenario_name,
                policy=self.policy.value,
                sim_time_s=round(curr_sim_time, 2),
                timestamp_iso=now_dt.isoformat(),
                origin_city=req.origin.city,
                target_node_id=target_id,
                target_level=decision.target_level.value,
                task_type=req.task_type.value,
                priority=req.priority.value,
                privacy=req.privacy.value,
                prompt_tokens=req.prompt_tokens_est,
                output_tokens=req.max_output_tokens,
                status="completed",
                latency_ms_simulated=round(total_lat, 2),
                network_rtt_ms_simulated=round(rtt_ms, 2),
                execution_time_ms_simulated=round(exec_time_ms + queue_wait_ms, 2),
                is_local_residency=is_local,
                is_outage_period=is_outage,
                edge_energy_j_simulated=round(edge_j, 2),
                cloud_energy_j_simulated=0.0,
                battery_soc_simulated=round(node_st.battery_soc, 4),
                renewable_share_simulated=round(renew_share, 4),
                reason=decision.reason,
            )
            self.records.append(rec)

    def run(self, trace: list[tuple[float, InferenceRequest]]) -> list[SimulationRecord]:
        """Execute the simulation for the provided request trace."""
        # Initial telemetry step
        self._update_telemetry(0.0, dt_seconds=5.0)
        self._last_telemetry_sim_time = 0.0

        # Start background simulation processes
        self.env.process(self._scenario_disturbances_process())

        # Workload generation process
        def _workload_driver():
            for arrival_s, req in trace:
                if arrival_s > self.env.now:
                    yield self.env.timeout(arrival_s - self.env.now)
                self.env.process(self._handle_request(req))

        self.env.process(_workload_driver())

        # Determine total duration: process all requests plus flush buffer
        if trace:
            last_req_s = max(t for t, _ in trace)
            duration_s = last_req_s + 60.0
        else:
            duration_s = float(self.scenario_params.get("duration_hours", 2.0)) * 3600.0

        self.env.run(until=duration_s)
        return self.records
