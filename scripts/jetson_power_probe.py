"""Jetson power and telemetry probe.

Provides unified readings across:
1. jtop (jetson-stats Python API)
2. tegrastats (/usr/bin/tegrastats subprocess)
3. Simulated/Mock fallback when not executing on physical hardware (strictly labelled).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PowerReading:
    timestamp: float
    power_w_measured: float
    ram_used_mb_measured: float
    ram_total_mb_measured: float
    temp_c_measured: float
    gpu_util_measured: float
    source: str  # 'jtop', 'tegrastats', or 'mock_host'
    nvpmodel_mode_measured: str


def get_nvpmodel_mode() -> str:
    """Query current nvpmodel power mode."""
    if shutil.which("nvpmodel"):
        try:
            res = subprocess.run(
                ["nvpmodel", "-q"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            # Example output: NV Power Mode: MAXN\n0
            match = re.search(r"NV Power Mode:\s*([^\n]+)", res.stdout)
            if match:
                return match.group(1).strip()
            return res.stdout.strip().replace("\n", " ")
        except Exception as e:
            logger.warning("Failed querying nvpmodel: %s", e)
    return "UNKNOWN"


class JetsonPowerProbe:
    """Monitors Jetson power, thermals, and memory utilization."""

    def __init__(self, sample_interval_s: float = 0.5):
        self.sample_interval_s = sample_interval_s
        self.nvpmodel_mode = get_nvpmodel_mode()
        self._jtop_instance = None
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        # Check jtop
        try:
            from jtop import jtop  # noqa: F401

            return "jtop"
        except ImportError:
            pass

        # Check tegrastats
        if shutil.which("tegrastats") or os.path.exists("/usr/bin/tegrastats"):
            return "tegrastats"

        logger.warning("Neither jtop nor tegrastats found. Using mock probe (non-Jetson host).")
        return "mock_host"

    def __enter__(self) -> JetsonPowerProbe:
        if self._backend == "jtop":
            from jtop import jtop

            self._jtop_instance = jtop(interval=self.sample_interval_s)
            self._jtop_instance.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._jtop_instance is not None:
            with contextlib.suppress(Exception):
                self._jtop_instance.close()
            self._jtop_instance = None

    def read_sample(self) -> PowerReading:
        """Capture one power snapshot."""
        now = time.time()

        if self._backend == "jtop" and self._jtop_instance:
            return self._read_jtop(now)
        elif self._backend == "tegrastats":
            return self._read_tegrastats(now)
        else:
            return self._read_mock(now)

    def _read_jtop(self, now: float) -> PowerReading:
        stats = self._jtop_instance.stats
        power_mw = stats.get("power", {}).get("tot", {}).get("power", 0.0)
        ram = stats.get("memory", {}).get("RAM", {})
        temp = stats.get("temperature", {}).get("CPU", {}).get("temp", 0.0)
        gpu = stats.get("GPU", 0.0)

        return PowerReading(
            timestamp=now,
            power_w_measured=power_mw / 1000.0 if power_mw else 0.0,
            ram_used_mb_measured=(ram.get("used", 0) / 1024.0),
            ram_total_mb_measured=(ram.get("tot", 0) / 1024.0),
            temp_c_measured=temp,
            gpu_util_measured=gpu / 100.0 if gpu else 0.0,
            source="jtop",
            nvpmodel_mode_measured=self.nvpmodel_mode,
        )

    def _read_tegrastats(self, now: float) -> PowerReading:
        tegrastats_path = shutil.which("tegrastats") or "/usr/bin/tegrastats"
        try:
            cmd = [tegrastats_path, "--interval", "100"]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            # Read first sample
            line = proc.stdout.readline() if proc.stdout else ""
            proc.terminate()

            # tegrastats output sample:
            # RAM 2841/7556MB ... VDD_IN 4512mW/4512mW ...
            ram_match = re.search(r"RAM\s+(\d+)/(\d+)MB", line)
            ram_used = float(ram_match.group(1)) if ram_match else 0.0
            ram_total = float(ram_match.group(2)) if ram_match else 0.0

            # Power extraction (VDD_IN or POM_5V_IN or VIN_SYS_5V0)
            power_match = re.search(r"(?:VDD_IN|POM_5V_IN|VIN_SYS_5V0)\s+(\d+)mW", line)
            power_w = float(power_match.group(1)) / 1000.0 if power_match else 0.0

            # Temp extraction
            temp_match = re.search(r"(?:CPU|cpu|soc0)@([\d\.]+)C", line)
            temp_c = float(temp_match.group(1)) if temp_match else 0.0

            # GPU util
            gpu_match = re.search(r"GR3D_FREQ\s+(\d+)%", line)
            gpu_util = float(gpu_match.group(1)) / 100.0 if gpu_match else 0.0

            return PowerReading(
                timestamp=now,
                power_w_measured=power_w,
                ram_used_mb_measured=ram_used,
                ram_total_mb_measured=ram_total,
                temp_c_measured=temp_c,
                gpu_util_measured=gpu_util,
                source="tegrastats",
                nvpmodel_mode_measured=self.nvpmodel_mode,
            )
        except Exception as e:
            logger.warning("tegrastats read failed: %s", e)
            return self._read_mock(now)

    def _read_mock(self, now: float) -> PowerReading:
        ram_used = 0.0
        ram_total = 0.0
        try:
            with open("/proc/meminfo") as f:
                meminfo = {}
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        meminfo[parts[0].strip()] = parts[1].strip()
                total_kb = float(meminfo.get("MemTotal", "0 kB").split()[0])
                avail_kb = float(meminfo.get("MemAvailable", "0 kB").split()[0])
                ram_total = total_kb / 1024.0
                ram_used = (total_kb - avail_kb) / 1024.0
        except Exception:
            pass

        return PowerReading(
            timestamp=now,
            power_w_measured=0.0,
            ram_used_mb_measured=round(ram_used, 1),
            ram_total_mb_measured=round(ram_total, 1),
            temp_c_measured=0.0,
            gpu_util_measured=0.0,
            source="mock_host",
            nvpmodel_mode_measured=self.nvpmodel_mode,
        )
