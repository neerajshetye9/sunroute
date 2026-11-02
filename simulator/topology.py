"""State-scale 30-city network topology and latency matrix.

Implements the 4-level hierarchy (local -> city -> region -> cloud)
and network graph representation using NetworkX.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx


@dataclass(frozen=True)
class CityInfo:
    """Metadata for a city in the state topology."""

    city_id: str
    name: str
    region: str
    x_km: float  # Cartesian coordinate for spatial distance
    y_km: float
    is_capital: bool = False


@dataclass
class TopologyConfig:
    """Configuration for state-scale 30-city network."""

    num_cities: int = 30
    nodes_per_city: int = 3  # 90 total edge nodes for full simulation trace
    base_intra_city_rtt_ms: float = 8.0
    base_intra_region_rtt_ms: float = 25.0
    base_cross_region_rtt_ms: float = 75.0
    cloud_rtt_ms: float = 90.0


class StateTopology:
    """Manages the 30-city network graph, spatial layout, and latency matrix."""

    def __init__(self, config: TopologyConfig | None = None, seed: int = 42) -> None:
        self.config = config or TopologyConfig()
        self.seed = seed
        self.cities: dict[str, CityInfo] = {}
        self.node_to_city: dict[str, str] = {}
        self.city_to_nodes: dict[str, list[str]] = {}
        self.region_to_cities: dict[str, list[str]] = {}
        self.graph = nx.Graph()

        self._init_topology()

    def _init_topology(self) -> None:
        """Initialize the 30 cities arranged into 5 geographic regions."""
        regions = {
            "region-central": (150.0, 150.0),  # Center
            "region-north": (150.0, 260.0),
            "region-south": (150.0, 40.0),
            "region-east": (260.0, 150.0),
            "region-west": (40.0, 150.0),
        }

        region_names = list(regions.keys())
        cities_per_region = self.config.num_cities // len(regions)

        city_idx = 1
        for r_name in region_names:
            rx, ry = regions[r_name]
            self.region_to_cities[r_name] = []
            for sub_i in range(cities_per_region):
                c_id = f"city-{city_idx:02d}"
                # Spread cities radially around regional center
                angle = 2.0 * math.pi * sub_i / cities_per_region
                dist = 25.0 + 10.0 * (sub_i % 2)
                cx = rx + dist * math.cos(angle)
                cy = ry + dist * math.sin(angle)
                is_cap = city_idx == 1  # city-01 is state capital & cloud DC

                info = CityInfo(
                    city_id=c_id,
                    name=f"City {city_idx}" + (" (Capital)" if is_cap else ""),
                    region=r_name,
                    x_km=round(cx, 1),
                    y_km=round(cy, 1),
                    is_capital=is_cap,
                )
                self.cities[c_id] = info
                self.region_to_cities[r_name].append(c_id)
                self.graph.add_node(c_id, **info.__dict__)

                # Populate nodes inside this city
                self.city_to_nodes[c_id] = []
                for n_idx in range(1, self.config.nodes_per_city + 1):
                    node_id = f"node-{c_id}-{n_idx}"
                    self.node_to_city[node_id] = c_id
                    self.city_to_nodes[c_id].append(node_id)

                city_idx += 1

        # Add graph edges with physical latencies
        city_ids = list(self.cities.keys())
        for i, c1 in enumerate(city_ids):
            for c2 in city_ids[i + 1 :]:
                rtt = self.calculate_rtt_ms(c1, c2)
                self.graph.add_edge(c1, c2, rtt_ms=rtt)

    def calculate_rtt_ms(self, city_a: str, city_b: str) -> float:
        """Calculate realistic network round-trip time between two cities."""
        if city_a == city_b:
            return self.config.base_intra_city_rtt_ms

        c_a = self.cities.get(city_a)
        c_b = self.cities.get(city_b)
        if not c_a or not c_b:
            return self.config.base_cross_region_rtt_ms

        if c_a.region == c_b.region:
            # Intra-region latency scaled by Euclidean distance
            dist = math.hypot(c_a.x_km - c_b.x_km, c_a.y_km - c_b.y_km)
            return round(self.config.base_intra_region_rtt_ms + (dist * 0.15), 2)
        else:
            # Cross-region latency
            dist = math.hypot(c_a.x_km - c_b.x_km, c_a.y_km - c_b.y_km)
            return round(self.config.base_cross_region_rtt_ms + (dist * 0.18), 2)

    def get_latency_to_node_ms(self, origin_city: str, target_node_id: str) -> float:
        """Get network RTT from origin city to target edge node."""
        target_city = self.node_to_city.get(target_node_id)
        if not target_city:
            # Target may be cloud
            return self.config.cloud_rtt_ms
        return self.calculate_rtt_ms(origin_city, target_city)

    def get_hierarchy_level(self, origin_city: str, target_node_id: str) -> str:
        """Determine hierarchy tier ('local', 'city', 'region', 'cloud') for a node."""
        target_city = self.node_to_city.get(target_node_id)
        if not target_city:
            return "cloud"
        if origin_city == target_city:
            return "local"

        c_orig = self.cities.get(origin_city)
        c_targ = self.cities.get(target_city)
        if c_orig and c_targ and c_orig.region == c_targ.region:
            return "region"

        return "cloud"  # Cross-regional trips escalate toward state level

    def get_nodes_in_level(self, origin_city: str, level: str) -> list[str]:
        """Fetch all node IDs eligible at a specific hierarchy level."""
        if level in ("local", "city"):
            return list(self.city_to_nodes.get(origin_city, []))

        if level == "region":
            orig_info = self.cities.get(origin_city)
            if not orig_info:
                return []
            regional_nodes: list[str] = []
            for c_id in self.region_to_cities.get(orig_info.region, []):
                if c_id != origin_city:
                    regional_nodes.extend(self.city_to_nodes.get(c_id, []))
            return regional_nodes

        if level == "cloud":
            # Cloud tier fallback
            return ["cloud-datacenter-01"]

        return []
