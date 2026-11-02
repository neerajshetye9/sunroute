# SunRoute

**Democratised Edge–Cloud AI Inference**

A research prototype of a community-owned network of edge nodes (societies, parks, campuses) powered by local solar, wind and battery, cooperating with one central cloud tier. Queries are routed to the best node by capacity, energy availability, locality and fairness — not first-come-first-served.

> **Status:** Research prototype. Not production-ready.

## Quick start

```bash
# Clone and install
git clone <repo-url> && cd sunroute
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Run tests
pytest
```

## Repository layout

```
├── CLAUDE.md                 # Project context (Sections 1-8, 10)
├── docs/                     # Architecture, API spec, routing policy, results
├── edge/                     # Jetson agent, energy rules, outbox, power probe
├── router/                   # Pure routing library, baselines, tests
├── gateway/                  # FastAPI gateway, decision log, dashboard API
├── simulator/                # Energy, workload, topology, scenarios (YAML)
├── virtual_nodes/            # Emulated nodes (Docker Compose, tc netem)
├── dashboard/                # React + Vite
├── cloud/                    # Lambda handlers, inference client, mock cloud
├── infra/                    # CloudFormation / CLI scripts
├── experiments/              # Runner, configs, raw logs, analysis
└── scripts/                  # Setup, benchmarks, export-before-expiry
```

## Key design principles

1. **Measure first, claim later** — every number is labelled *measured*, *simulated*, or *estimated*
2. **Honest framing** — we do not claim edge saves energy per token; we measure and report
3. **Democracy metrics** — fairness, ownership, resilience, locality, not just efficiency
4. **Pure routing** — `route()` is a unit-tested pure function, no side effects
5. **Config over code** — weights, thresholds and scenarios in YAML

See [docs/build-plan.md](docs/build-plan.md) for the full build plan and [CLAUDE.md](CLAUDE.md) for project context.

## License

MIT
