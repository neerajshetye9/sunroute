#!/usr/bin/env python3
"""SunRoute: Record Jetson Idle Power.

Samples baseline idle power using jtop or tegrastats over a specified duration
with the system at rest (no background inference).
Output is saved to a CSV with all metrics labelled `measured`.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.jetson_power_probe import JetsonPowerProbe  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("record_idle_power")


def record_idle_power(
    duration_s: float,
    interval_s: float,
    output_csv: Path,
) -> None:
    logger.info(
        "Recording idle power for %.1f seconds at %.2f s intervals...", duration_s, interval_s
    )
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    samples = []
    start_time = time.time()

    with JetsonPowerProbe(sample_interval_s=interval_s) as probe:
        mode = probe.nvpmodel_mode
        logger.info("Jetson nvpmodel mode: %s | Probe backend: %s", mode, probe._backend)
        if probe._backend == "mock_host":
            logger.warning("Running on non-Jetson environment. Power readings will be 0.0W.")

        while (time.time() - start_time) < duration_s:
            reading = probe.read_sample()
            samples.append(reading)
            time.sleep(interval_s)

    if not samples:
        logger.error("No samples collected.")
        return

    # Write samples to CSV
    fieldnames = [
        "timestamp_iso",
        "elapsed_s",
        "nvpmodel_mode_measured",
        "idle_power_w_measured",
        "ram_used_mb_measured",
        "ram_total_mb_measured",
        "temp_c_measured",
        "gpu_util_measured",
        "probe_backend_measured",
        "metric_classification",  # always 'measured'
    ]

    with open(output_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, s in enumerate(samples):
            writer.writerow(
                {
                    "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s.timestamp)),
                    "elapsed_s": round(idx * interval_s, 2),
                    "nvpmodel_mode_measured": s.nvpmodel_mode_measured,
                    "idle_power_w_measured": round(s.power_w_measured, 3),
                    "ram_used_mb_measured": round(s.ram_used_mb_measured, 1),
                    "ram_total_mb_measured": round(s.ram_total_mb_measured, 1),
                    "temp_c_measured": round(s.temp_c_measured, 1),
                    "gpu_util_measured": round(s.gpu_util_measured, 3),
                    "probe_backend_measured": s.source,
                    "metric_classification": "measured",
                }
            )

    # Compute summary
    powers = [s.power_w_measured for s in samples]
    mean_power = sum(powers) / len(powers)
    min_power = min(powers)
    max_power = max(powers)

    print("\n" + "=" * 60)
    print("SUNROUTE JETSON IDLE POWER MEASUREMENT SUMMARY")
    print("=" * 60)
    print(f"Total duration:            {duration_s:.1f} s")
    print(f"Samples collected:         {len(samples)}")
    print(f"Power mode (nvpmodel):     {mode}")
    print(f"Probe backend:             {samples[0].source}")
    print(f"Mean idle power:           {mean_power:.3f} W [measured]")
    print(f"Min idle power:            {min_power:.3f} W [measured]")
    print(f"Max idle power:            {max_power:.3f} W [measured]")
    print(f"CSV exported to:           {output_csv}")
    print("=" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record Jetson idle power baseline.")
    parser.add_argument(
        "--duration-s",
        type=float,
        default=60.0,
        help="Sampling window duration in seconds (default: 60)",
    )
    parser.add_argument(
        "--interval-s",
        type=float,
        default=1.0,
        help="Sampling interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=PROJECT_ROOT / "docs" / "results" / "idle_power.csv",
        help="Path to output CSV file",
    )
    args = parser.parse_args()

    record_idle_power(
        duration_s=args.duration_s,
        interval_s=args.interval_s,
        output_csv=args.output_csv,
    )


if __name__ == "__main__":
    main()
