#!/usr/bin/env bash
# Apply tc netem latency and packet jitter to virtual edge node containers
# to emulate physical inter-city geographic network distances.

set -euo pipefail

echo "Applying network emulation (tc netem) to virtual edge nodes..."

# City 01: Local low latency (8ms +/- 1ms)
if docker ps --format '{{.Names}}' | grep -q "sunroute-node-city-01"; then
    echo "Configuring sunroute-node-city-01 (8ms RTT)..."
    docker exec --privileged sunroute-node-city-01 tc qdisc replace dev eth0 root netem delay 8ms 1ms
fi

# City 02: Intra-regional neighbor (25ms +/- 3ms)
if docker ps --format '{{.Names}}' | grep -q "sunroute-node-city-02"; then
    echo "Configuring sunroute-node-city-02 (25ms RTT)..."
    docker exec --privileged sunroute-node-city-02 tc qdisc replace dev eth0 root netem delay 25ms 3ms
fi

# City 05: Remote cross-region (75ms +/- 10ms, 0.1% loss)
if docker ps --format '{{.Names}}' | grep -q "sunroute-node-city-05"; then
    echo "Configuring sunroute-node-city-05 (75ms RTT, 0.1% loss)..."
    docker exec --privileged sunroute-node-city-05 tc qdisc replace dev eth0 root netem delay 75ms 10ms loss 0.1%
fi

echo "tc netem network emulation configured successfully."
