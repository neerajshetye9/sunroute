# Assumptions and Limitations

## Hardware assumptions

- **Jetson Orin Nano Super 8 GB**: aarch64, L4T R39.2.1, JetPack 7.2, sm_87 CUDA architecture
- Power measurements are from the Jetson's built-in power rail monitors via `jtop` or `tegrastats`
- Energy measurements on virtual/emulated nodes are **simulated**, calibrated from real Jetson measurements

## Software assumptions

- llama.cpp built natively on Jetson with CUDA (not relying on third-party containers for JetPack 7.2)
- Models are GGUF format, quantised, 1–3B parameters for edge
- Python 3.11+ on all components

## AWS assumptions

- Lab account with approximately 24-hour access, permission-limited
- Available services **must be verified** by the capability-check script before use
- No AWS IAM keys stored on the Jetson
- All AWS integration has a documented mock fallback

## Simulation assumptions

- Solar irradiance from pvlib with location-specific parameters
- Wind from Weibull distribution with power curve
- Battery modelled as simple SOC with charge/discharge efficiency
- Network latency from a distance-based matrix with jitter
- All simulation parameters are documented and sensitivity-tested

## What this project is NOT

- Not a production system
- Not a claim that edge is more energy-efficient per token than cloud
- Not a new idea without literature verification
- Not blockchain-based

## Known limitations

- Single physical edge node (Jetson); scale is simulated
- AWS access is temporary; results may use mock cloud
- Energy measurements on the Jetson are from built-in monitors, not external power meters
- Quality evaluation is on a small set of labelled tasks, not comprehensive
