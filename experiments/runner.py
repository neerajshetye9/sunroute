"""Unified experiment runner for SunRoute evaluations.

Executes identical seeded traces across:
- 8 Scenarios (sunny_day, cloudy_day, night_low_battery, windy_evening,
               internet_outage_30min, node_failure, city_blackout, traffic_spike)
- 5 Policies (cloud_only, edge_only, fcfs, cascade, proposed)
- Multiple repeats

Logs all raw events to DuckDB / Parquet and computes Section 7 metrics.
All outputs carry explicit '_simulated' or '_estimated' suffixes per Section 3.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

from router.schemas import PolicyType, RouterConfig
from simulator.sim_engine import SimulationEngine, SimulationRecord
from simulator.topology import TopologyConfig
from simulator.workload import WorkloadConfig, WorkloadGenerator

logger = logging.getLogger("experiments.runner")


def calculate_gini(values: list[float] | np.ndarray) -> float:
    """Calculate Gini coefficient of service distribution across nodes."""
    arr = np.array(values, dtype=np.float64)
    if len(arr) == 0 or np.all(arr == 0):
        return 0.0
    arr = np.sort(arr)
    n = len(arr)
    index = np.arange(1, n + 1)
    return float((np.sum((2 * index - n - 1) * arr)) / (n * np.sum(arr)))


class ExperimentRunner:
    """Orchestrates scenario and policy matrix execution."""

    def __init__(
        self,
        config_path: Path | str = "config/default.yaml",
        scenarios_path: Path | str = "config/scenarios.yaml",
        output_dir: Path | str = "experiments/results",
        duckdb_path: Path | str = "experiments/experiments.duckdb",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.duckdb_path = Path(duckdb_path)

        with open(config_path, encoding="utf-8") as f:
            self.default_cfg_dict = yaml.safe_load(f)
        with open(scenarios_path, encoding="utf-8") as f:
            scenarios_raw = yaml.safe_load(f)
            self.scenarios = scenarios_raw.get("scenarios", {})

        self.router_config = RouterConfig.from_dict(self.default_cfg_dict)

    def run_experiment(
        self,
        scenario_name: str,
        policy: PolicyType,
        seed: int = 42,
        num_requests: int = 150,
    ) -> list[SimulationRecord]:
        """Run a single (scenario, policy, seed) experiment on an identical trace."""
        scenario_params = self.scenarios.get(scenario_name, {})
        duration_hours = scenario_params.get("duration_hours", 2.0)

        # Generate identical deterministic trace
        topo = TopologyConfig()
        cities = [f"city-{i:02d}" for i in range(1, topo.num_cities + 1)]
        workload_gen = WorkloadGenerator(
            cities=cities,
            config=WorkloadConfig(
                total_requests=num_requests,
                duration_hours=duration_hours,
                seed=seed,
            ),
        )
        trace = workload_gen.generate_trace(
            start_time=datetime(2026, 6, 21, 10, 0, tzinfo=UTC),
            scenario_params=scenario_params,
        )

        # Execute simulation engine
        engine = SimulationEngine(
            scenario_name=scenario_name,
            scenario_params=scenario_params,
            policy=policy,
            router_config=self.router_config,
            topology_config=topo,
            seed=seed,
        )
        return engine.run(trace)

    def run_matrix(
        self,
        scenarios: list[str] | None = None,
        policies: list[str] | None = None,
        repeats: int = 1,
        num_requests: int = 150,
    ) -> pd.DataFrame:
        """Run full or partial matrix of scenarios x policies x repeats."""
        target_scenarios = scenarios or list(self.scenarios.keys())
        target_policies = [PolicyType(p) for p in (policies or [p.value for p in PolicyType])]

        all_records: list[SimulationRecord] = []

        for s_name in target_scenarios:
            for pol in target_policies:
                for rep in range(repeats):
                    seed = 42 + rep * 1007
                    records = self.run_experiment(
                        scenario_name=s_name,
                        policy=pol,
                        seed=seed,
                        num_requests=num_requests,
                    )
                    all_records.extend(records)

        # Convert to pandas DataFrame
        df = pd.DataFrame([asdict(r) for r in all_records])
        if not df.empty:
            self._save_results(df)
        return df

    def _save_results(self, df: pd.DataFrame) -> None:
        """Save results to Parquet and DuckDB database."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        parquet_path = self.output_dir / f"sim_results_{timestamp}.parquet"
        df.to_parquet(parquet_path, index=False)

        # Ingest to DuckDB
        con = duckdb.connect(str(self.duckdb_path))
        con.execute("CREATE TABLE IF NOT EXISTS simulation_events AS SELECT * FROM df WHERE 1=0")
        con.register("df_temp", df)
        con.execute("INSERT INTO simulation_events SELECT * FROM df_temp")
        con.close()

    @staticmethod
    def compute_summary_metrics(df: pd.DataFrame) -> pd.DataFrame:
        """Compute Section 7 summary metrics grouped by scenario and policy."""
        summaries = []

        for (scenario, policy), grp in df.groupby(["scenario", "policy"]):
            total_reqs = len(grp)
            completed = grp[grp["status"] == "completed"]
            comp_count = len(completed)

            # Democracy metrics
            edge_completed = completed[completed["target_level"] != "cloud"]
            community_share = len(edge_completed) / max(1, comp_count)

            node_counts = edge_completed["target_node_id"].value_counts().values
            gini = calculate_gini(node_counts) if len(node_counts) > 0 else 0.0
            worst_served = int(node_counts.min()) if len(node_counts) > 0 else 0

            essential_reqs = grp[grp["priority"] == "essential"]
            essential_served = essential_reqs[essential_reqs["status"] == "completed"]
            essential_rate = len(essential_served) / max(1, len(essential_reqs))

            # Resilience
            outage_reqs = grp[grp["is_outage_period"]]
            outage_served = len(outage_reqs[outage_reqs["status"] == "completed"])

            # Locality & Privacy
            local_residency_rate = completed["is_local_residency"].mean() if comp_count > 0 else 0.0
            privacy_reqs = grp[grp["privacy"] == "local_only"]
            priv_comp = privacy_reqs[privacy_reqs["status"] == "completed"]
            data_residency_rate = (
                priv_comp["is_local_residency"].mean() if len(priv_comp) > 0 else 1.0
            )

            # Energy
            total_edge_wh = completed["edge_energy_j_simulated"].sum() / 3600.0
            total_cloud_wh = completed["cloud_energy_j_simulated"].sum() / 3600.0
            mean_renew_share = (
                completed["renewable_share_simulated"].mean() if comp_count > 0 else 0.0
            )

            # Latency
            p50_lat = (
                float(completed["latency_ms_simulated"].quantile(0.50)) if comp_count > 0 else 0.0
            )
            p95_lat = (
                float(completed["latency_ms_simulated"].quantile(0.95)) if comp_count > 0 else 0.0
            )

            # Cloud Load
            cloud_reqs = len(completed[completed["target_level"] == "cloud"])

            summaries.append(
                {
                    "scenario": scenario,
                    "policy": policy,
                    "total_requests": total_reqs,
                    "completed_requests": comp_count,
                    "community_share_simulated": round(community_share, 4),
                    "gini_fairness_simulated": round(gini, 4),
                    "worst_served_node_queries": worst_served,
                    "essential_service_rate": round(essential_rate, 4),
                    "outage_served_requests": outage_served,
                    "local_residency_rate_simulated": round(local_residency_rate, 4),
                    "data_residency_rate_simulated": round(data_residency_rate, 4),
                    "edge_energy_wh_simulated": round(total_edge_wh, 4),
                    "cloud_energy_wh_estimated": round(total_cloud_wh, 4),
                    "renewable_share_simulated": round(mean_renew_share, 4),
                    "p50_latency_ms_simulated": round(p50_lat, 2),
                    "p95_latency_ms_simulated": round(p95_lat, 2),
                    "cloud_request_count": cloud_reqs,
                }
            )

        return pd.DataFrame(summaries)


def main() -> None:
    """CLI for running SunRoute experiment matrix."""
    parser = argparse.ArgumentParser(description="SunRoute Simulation Experiment Runner")
    parser.add_argument("--scenarios", type=str, default=None, help="Comma-separated scenario list")
    parser.add_argument("--policies", type=str, default=None, help="Comma-separated policy list")
    parser.add_argument("--repeats", type=int, default=1, help="Number of random seed repeats")
    parser.add_argument("--requests", type=int, default=100, help="Number of requests per run")
    args = parser.parse_args()

    scenarios = args.scenarios.split(",") if args.scenarios else None
    policies = args.policies.split(",") if args.policies else None

    runner = ExperimentRunner()
    print(f"Running experiments (repeats={args.repeats}, requests={args.requests})...")
    df = runner.run_matrix(
        scenarios=scenarios,
        policies=policies,
        repeats=args.repeats,
        num_requests=args.requests,
    )
    summary = ExperimentRunner.compute_summary_metrics(df)
    print("\n=== Experiment Summary Metrics ===")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
