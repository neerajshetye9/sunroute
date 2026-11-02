# SunRoute

**Democratised Edge–Cloud AI Inference**

A research prototype of a community-owned network of edge nodes (societies, parks, campuses) powered by local solar, wind and battery, cooperating with one central cloud tier. Queries are routed to the best node by capacity, energy availability, locality and fairness — not first-come-first-served.

> **Status:** Research prototype. Not production-ready.

## Quick start

### 1. Installation & Environment Setup
```bash
# Clone and enter directory
git clone https://github.com/neerajshetye9/sunroute.git && cd sunroute

# Create virtual environment and install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Verify complete test suite (54 tests)
pytest
```

### 2. Run Local Loop End-to-End
Execute local edge inference, energy admission rules, SQLite durable outbox, pure router, and gateway decision audit log on a single command:
```bash
source .venv/bin/activate
export PYTHONPATH=.
python scripts/run_local_loop.py
```

### 3. Run Research Evaluation Matrix & Hypothesis Validation
Execute the full 8-scenario x 5-policy matrix and multi-objective ablation studies on the 30-city discrete simulation:
```bash
source .venv/bin/activate
export PYTHONPATH=.
python scripts/run_evaluation_matrix.py
```
*Results and empirical hypothesis verdicts are compiled to [`docs/results/evaluation-report.md`](docs/results/evaluation-report.md).*

### 4. Launch Live Telemetry Dashboard & Gateway
Start the FastAPI Gateway with real-time SSE streaming:
```bash
source .venv/bin/activate
export PYTHONPATH=.
uvicorn gateway.app:app --host 0.0.0.0 --port 8000
```
In a separate terminal, launch the React 18 + Vite dashboard:
```bash
cd dashboard
npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser. All metrics display explicit `[SIMULATED]`, `[MEASURED]`, or `[ESTIMATED]` badges.

---

## Hardware & Cloud Tools

### Jetson Orin Nano Super 8GB (aarch64)
- **Power Probe & Idle Measurement**: `python scripts/jetson_power_probe.py` / `python scripts/record_idle_power.py`
- **Native llama.cpp Build**: `bash scripts/build_llama_cpp.sh`
- **GGUF Model Benchmark**: `python scripts/benchmark_model.py --model models/llama-3.2-1b.gguf`

### AWS Integration (Serverless Telemetry & Bedrock)
- **Capability Audit**: `python scripts/check_aws_capabilities.py` (probes STS, Bedrock, Lambda, SQS, DynamoDB, S3)
- **CloudFormation Ingestion Pipeline**: `infra/telemetry-pipeline.yaml`
- **Outbox Pusher Daemon**: `python edge/telemetry_pusher.py` (outbound-only HTTPS to API Gateway)
- **Pre-expiry State Export**: `bash scripts/export_before_expiry.sh`

---

## Repository layout

```
├── CLAUDE.md                 # Project context & architecture rules (Sections 1-8, 10)
├── docs/                     # Architecture, API spec, routing policy, evaluation report
├── edge/                     # Jetson agent, energy rules, outbox, power probe
├── router/                   # Pure routing library, scoring, fairness ledger, baselines
├── gateway/                  # FastAPI gateway, decision log, dashboard SSE/REST API
├── simulator/                # pvlib solar, Weibull wind, SimPy discrete engine, 30-city topology
├── virtual_nodes/            # Emulated nodes (Docker Compose, tc netem)
├── dashboard/                # React 18 + Vite + TypeScript telemetry dashboard
├── cloud/                    # Bedrock client, Lambda handlers, mock cloud fallback
├── infra/                    # CloudFormation pipeline (API GW -> SQS -> Lambda -> DynamoDB/S3)
├── experiments/              # Matrix runner, DuckDB/Parquet exporters
└── scripts/                  # Jetson setup, benchmarks, evaluation matrix runner
```

## Key design principles

1. **Measure first, claim later** — every number is labelled *measured*, *simulated*, or *estimated*.
2. **Honest framing** — we do not claim edge saves energy per token; hyperscale cloud data centers remain vastly more efficient at batch processing. The justification for edge is ownership, resilience, data sovereignty, and clean energy scavenging.
3. **Democracy metrics** — fairness, community ownership, resilience, locality, not just efficiency.
4. **Pure routing** — `route()` is a unit-tested pure function with zero clock or network side-effects.
5. **Config over code** — weights, thresholds, and scenarios are strictly versioned in YAML.

See [docs/build-plan.md](docs/build-plan.md) for the milestone tracker and [docs/results/evaluation-report.md](docs/results/evaluation-report.md) for empirical results.

## License

MIT
