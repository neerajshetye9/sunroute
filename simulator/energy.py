"""Energy generation, storage, and consumption models for edge nodes.

All metrics produced by this module carry explicit '_simulated' suffixes per Section 3.
Models:
- Solar: clear-sky GHI with diurnal curve via pvlib, scaled by panel rating and scenario factor.
- Wind: Weibull distribution and cubic turbine power curve, scaled by scenario factor.
- Battery: finite capacity (Wh) with charge/discharge efficiencies and SOC clamping.
- Node energy: combines renewables, idle power, and inference workload.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
import pvlib


@dataclass
class SolarConfig:
    """Configuration for small edge solar panel."""

    rated_power_w: float = 40.0  # e.g., 40W compact community panel
    latitude: float = 19.0760  # State scale (e.g., Mumbai / Maharashtra)
    longitude: float = 72.8777
    tz: str = "Asia/Kolkata"


_GHI_CACHE: dict[tuple[float, float, str, int], float] = {}


class SolarModel:
    """Deterministic, seeded solar generation model based on pvlib."""

    def __init__(self, config: SolarConfig | None = None, seed: int = 42) -> None:
        self.config = config or SolarConfig()
        self.seed = seed
        self.location = pvlib.location.Location(
            latitude=self.config.latitude,
            longitude=self.config.longitude,
            tz=self.config.tz,
        )

    def power_w(self, timestamp: datetime, solar_factor: float = 1.0) -> float:
        """Calculate solar power output (Watts) at a given timestamp.

        solar_factor: 1.0 (clear sky), 0.2 (cloudy), 0.0 (night).
        """
        if solar_factor <= 0.0:
            return 0.0

        ts_minute = int(timestamp.timestamp() // 60)
        cache_key = (
            self.config.latitude,
            self.config.longitude,
            ts_minute,
        )
        if cache_key in _GHI_CACHE:
            ghi = _GHI_CACHE[cache_key]
        else:
            ts_series = pd.DatetimeIndex([timestamp])
            if ts_series.tz is None:
                ts_series = ts_series.tz_localize(self.config.tz)
            else:
                ts_series = ts_series.tz_convert(self.config.tz)
            clearsky = self.location.get_clearsky(ts_series)
            ghi = float(clearsky["ghi"].iloc[0])
            _GHI_CACHE[cache_key] = ghi

        # Scale GHI to panel rated capacity (1000 W/m^2 = 100% rated output)
        nominal_fraction = max(0.0, min(1.0, ghi / 1000.0))
        power = nominal_fraction * self.config.rated_power_w * solar_factor
        return round(max(0.0, power), 3)


@dataclass
class WindConfig:
    """Configuration for micro-wind turbine at an edge site."""

    rated_power_w: float = 20.0
    cut_in_speed_ms: float = 2.5
    rated_speed_ms: float = 9.0
    cut_out_speed_ms: float = 18.0
    weibull_k: float = 2.0  # Rayleigh shape
    weibull_c: float = 4.5  # Mean scale parameter in m/s


class WindModel:
    """Wind generation model using Weibull distribution and turbine power curve."""

    def __init__(self, config: WindConfig | None = None, seed: int = 42) -> None:
        self.config = config or WindConfig()
        self.seed = seed
        # Deterministic pseudo-random state
        self._rng = (seed * 1103515245 + 12345) & 0x7FFFFFFF

    def _next_rand(self) -> float:
        self._rng = (self._rng * 1103515245 + 12345) & 0x7FFFFFFF
        return self._rng / float(0x7FFFFFFF)

    def power_w(self, sim_second: float, wind_factor: float = 1.0) -> float:
        """Calculate wind power output (Watts) at simulation elapsed second."""
        if wind_factor <= 0.0:
            return 0.0

        # Deterministic continuous wind variation with periodic gusts + pseudo-random Weibull noise
        # Base diurnal/hourly wind modulation + seeded turbulence
        hour = (sim_second / 3600.0) % 24.0
        # Wind is typically slightly stronger in late afternoon / evening
        diurnal_mult = 0.8 + 0.4 * math.sin((hour - 14.0) * math.pi / 12.0)

        # Invert CDF of Weibull: v = c * (-ln(1 - u))^(1/k)
        u = max(0.001, min(0.999, self._next_rand()))
        v_instant = self.config.weibull_c * ((-math.log(1.0 - u)) ** (1.0 / self.config.weibull_k))
        v = v_instant * diurnal_mult * wind_factor

        # Power curve: cubic ramp between cut-in and rated speed
        if v < self.config.cut_in_speed_ms or v >= self.config.cut_out_speed_ms:
            return 0.0
        elif v >= self.config.rated_speed_ms:
            return round(self.config.rated_power_w * wind_factor, 3)
        else:
            fraction = (v - self.config.cut_in_speed_ms) / (
                self.config.rated_speed_ms - self.config.cut_in_speed_ms
            )
            power = self.config.rated_power_w * (fraction**3) * wind_factor
            return round(max(0.0, power), 3)


@dataclass
class BatteryConfig:
    """Configuration for local edge battery pack (e.g. 12V 5Ah LiFePO4)."""

    capacity_wh: float = 60.0
    initial_soc: float = 0.80
    reserve_soc: float = 0.20
    critical_soc: float = 0.10
    charge_efficiency: float = 0.90
    discharge_efficiency: float = 0.95


class BatteryModel:
    """State-of-charge tracking battery model."""

    def __init__(self, config: BatteryConfig | None = None) -> None:
        self.config = config or BatteryConfig()
        self.soc: float = self.config.initial_soc
        self.floor_violations: int = 0

    def update(self, net_power_w: float, dt_seconds: float) -> tuple[float, bool]:
        """Update battery state given net power (Generation - Load).

        net_power_w: > 0 means net surplus (charging), < 0 means net deficit (discharging).
        dt_seconds: duration of time step in seconds.
        Returns: (new_soc, is_below_reserve_floor)
        """
        hours = dt_seconds / 3600.0
        if net_power_w >= 0.0:
            # Charging
            delta_wh = net_power_w * self.config.charge_efficiency * hours
            self.soc += delta_wh / self.config.capacity_wh
        else:
            # Discharging
            deficit_wh = abs(net_power_w) * hours / self.config.discharge_efficiency
            self.soc -= deficit_wh / self.config.capacity_wh

        self.soc = max(0.0, min(1.0, self.soc))

        if self.soc < self.config.critical_soc:
            self.floor_violations += 1

        is_reserve = self.soc <= self.config.reserve_soc
        return self.soc, is_reserve


class NodeEnergySimulator:
    """Combines solar, wind, battery, and dynamic workload for an individual edge node."""

    def __init__(
        self,
        node_id: str,
        city: str,
        solar_config: SolarConfig | None = None,
        wind_config: WindConfig | None = None,
        battery_config: BatteryConfig | None = None,
        idle_power_w: float = 4.987,  # Calibrated Jetson Orin Nano Super idle [measured]
        active_power_w: float = 9.557,  # Calibrated Jetson Orin Nano Super GPU load [measured]
        seed: int = 42,
    ) -> None:
        self.node_id = node_id
        self.city = city
        self.idle_power_w = idle_power_w
        self.active_power_w = active_power_w
        self.solar = SolarModel(solar_config, seed=seed)
        self.wind = WindModel(wind_config, seed=seed + 101)
        self.battery = BatteryModel(battery_config)

    def step(
        self,
        sim_timestamp: datetime,
        sim_second: float,
        dt_seconds: float,
        is_inferring: bool,
        solar_factor: float = 1.0,
        wind_factor: float = 1.0,
    ) -> dict[str, Any]:
        """Step energy simulation forward by dt_seconds.

        Returns telemetry dictionary with explicit '_simulated' suffixes.
        """
        p_solar = self.solar.power_w(sim_timestamp, solar_factor)
        p_wind = self.wind.power_w(sim_second, wind_factor)
        p_gen = p_solar + p_wind

        p_load = self.active_power_w if is_inferring else self.idle_power_w
        net_power = p_gen - p_load

        soc, is_reserve = self.battery.update(net_power, dt_seconds)

        return {
            "node_id": self.node_id,
            "city": self.city,
            "solar_w_simulated": round(p_solar, 2),
            "wind_w_simulated": round(p_wind, 2),
            "generation_w_simulated": round(p_gen, 2),
            "load_w_simulated": round(p_load, 2),
            "net_power_w_simulated": round(net_power, 2),
            "battery_soc_simulated": round(soc, 4),
            "is_reserve_floor": is_reserve,
            "is_critical_soc": soc < self.battery.config.critical_soc,
            "energy_source": "simulated",
            "timestamp": sim_timestamp.isoformat(),
        }
