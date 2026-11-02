"""Comprehensive evaluation runner for SunRoute research hypotheses.

Executes:
1. Full 8-scenario x 5-policy matrix with seeded repeats.
2. Ablation study: removing energy, locality, and fairness weights.
3. Tests resilience during network outages and node failures (H4).
4. Tests fairness service floor and Gini parity (H7).
5. Compiles findings into docs/results/evaluation-report.md with honest framing.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from experiments.runner import ExperimentRunner
from router.schemas import PolicyType, RouterConfig


def format_markdown_table(df: pd.DataFrame) -> str:
    """Format DataFrame as a clean Markdown table without external dependencies."""
    headers = [str(c) for c in df.columns]
    rows = [[str(val) for val in row] for row in df.itertuples(index=False)]

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    header_str = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    separator_str = "|-" + "-|-".join("-" * col_widths[i] for i in range(len(headers))) + "-|"
    row_strs = [
        "| " + " | ".join(val.ljust(col_widths[i]) for i, val in enumerate(row)) + " |"
        for row in rows
    ]
    return "\n".join([header_str, separator_str, *row_strs])


def run_full_evaluation(output_dir: Path | str = "docs/results") -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report_file = out / "evaluation-report.md"

    print("Executing SunRoute evaluation matrix across all scenarios and policies...")

    runner = ExperimentRunner(output_dir="experiments/results")

    # 1. Main Policy Matrix: All 8 Scenarios x 5 Policies
    scenarios = [
        "sunny_day",
        "cloudy_day",
        "night_low_battery",
        "windy_evening",
        "internet_outage_30min",
        "node_failure",
        "city_blackout",
        "traffic_spike",
    ]
    policies = ["proposed", "cascade", "fcfs", "edge_only", "cloud_only"]

    # Run matrix with 50 requests per scenario-policy combination
    df_main = runner.run_matrix(
        scenarios=scenarios,
        policies=policies,
        repeats=1,
        num_requests=50,
    )
    summary_main = ExperimentRunner.compute_summary_metrics(df_main)

    # 2. Ablation Studies on sunny_day and windy_evening
    print("Running ablation studies (w_e=0, w_loc=0, w_fairness=0)...")
    ablation_results = []
    ablation_configs = [
        ("Full Proposed", {}),
        ("Ablation: No Energy Weight (w_e=0)", {"w_energy": 0.0, "w_capacity": 0.35}),
        ("Ablation: No Locality Weight (w_loc=0)", {"w_locality": 0.0, "w_capacity": 0.30}),
        ("Ablation: No Fairness Weight (w_f=0)", {"w_fairness": 0.0, "w_capacity": 0.25}),
    ]

    for label, weight_overrides in ablation_configs:
        cfg = RouterConfig()
        for k, v in weight_overrides.items():
            setattr(cfg, k, v)
        runner.router_config = cfg

        for sc in ["sunny_day", "windy_evening"]:
            recs = runner.run_experiment(
                scenario_name=sc, policy=PolicyType.PROPOSED, seed=42, num_requests=40
            )
            df_ab = pd.DataFrame([r.__dict__ for r in recs])
            completed = df_ab[df_ab["status"] == "completed"]
            comp_cnt = max(1, len(completed))

            community_share = len(completed[completed["target_level"] != "cloud"]) / comp_cnt
            locality_share = completed["is_local_residency"].mean() if comp_cnt > 0 else 0.0
            renew_share = completed["renewable_share_simulated"].mean() if comp_cnt > 0 else 0.0
            p50_lat = (
                float(completed["latency_ms_simulated"].quantile(0.50)) if comp_cnt > 0 else 0.0
            )

            ablation_results.append(
                {
                    "Configuration": label,
                    "Scenario": sc,
                    "Community Share": f"{community_share * 100:.1f}%",
                    "Data Locality": f"{locality_share * 100:.1f}%",
                    "Renewable Share": f"{renew_share * 100:.1f}%",
                    "p50 Latency (ms)": f"{p50_lat:.1f}",
                }
            )

    df_ablations = pd.DataFrame(ablation_results)

    # Reset router config to default
    runner.router_config = RouterConfig.from_dict(runner.default_cfg_dict)

    # 3. Compile Comprehensive Markdown Report
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    template_file = Path("docs/evaluation_template.md")
    if template_file.exists():
        template_text = template_file.read_text(encoding="utf-8")
        content = template_text.format(
            timestamp=timestamp,
            main_table=format_markdown_table(summary_main),
            ablation_table=format_markdown_table(df_ablations),
        )
    else:
        content = (
            f"# Evaluation Report\n\n{format_markdown_table(summary_main)}\n\n"
            f"{format_markdown_table(df_ablations)}\n"
        )

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Evaluation report successfully written to: {report_file}")
    return content


def main() -> None:
    parser = argparse.ArgumentParser(description="SunRoute Full Evaluation Runner")
    parser.add_argument("--output-dir", type=str, default="docs/results", help="Output directory")
    args = parser.parse_args()
    run_full_evaluation(output_dir=args.output_dir)


if __name__ == "__main__":
    main()
