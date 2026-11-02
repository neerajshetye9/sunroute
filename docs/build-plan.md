# Build Plan

> This is the step-by-step build plan (Section 9 of the project specification).
> Each phase has exit checks that must pass before moving to the next.

## Phase 0: Foundation

- [x] git init, repo layout, .gitignore (secrets, models, logs), pre-commit secrets scan
- [x] Jetson: verify JetPack, CUDA and nvpmodel mode; install jtop; record idle power (`scripts/record_idle_power.py`, `scripts/jetson_power_probe.py`)
- [x] Build llama.cpp natively on the Jetson with CUDA for the Orin architecture (sm_87). (`scripts/build_llama_cpp.sh`)
- [x] Python environment with pinned dependencies (`pyproject.toml`)
- [x] AWS capability check script and report (`scripts/check_aws_capabilities.py`, `docs/aws-capability-report.md`)
- [x] Write docs/assumptions-and-limits.md

**Exit:** Jetson answers a prompt locally; idle and load power recorded. (PASSED)

## Phase 1: Measure first

- [x] Benchmark 2–3 quantised models of about 1–3 B parameters: tokens/s, TTFT, RAM, watts, joules/token (`scripts/benchmark_model.py`)
- [x] Measure the same for the cloud model when available
- [x] Pick one model for the edge by speed versus quality (Llama-3.2-1B-Instruct-Q4_K_M)

**Exit:** Results table with `measured` labels. These numbers calibrate everything else. (PASSED)

## Phase 2: Core software (no AWS needed)

- [x] OpenAPI spec for edge and gateway
- [x] Edge agent: `/infer`, `/state`, `/health`, auth, validation, rate and size limits
- [x] Deterministic energy rules plus unit tests
- [x] SQLite outbox: retry with backoff and jitter, expiry, idempotency, failure-injection tests
- [x] Router library: hard filters, scoring, locality, fairness ledger, power of two choices, baselines (cloud-only, FCFS, cascade), unit tests
- [x] Mock cloud with the same interface as the AWS client
- [x] Gateway with append-only decision log

**Exit:** Full local loop runs end to end on one command. (PASSED)

## Phase 3: Simulation at scale

- [x] Energy simulator (solar via pvlib, wind via Weibull and power curve, battery SOC, demand with bursts), seeded
- [x] SimPy topology: 30 cities, hundreds to thousands of nodes, hierarchy, latency matrix
- [x] Virtual nodes calibrated from Phase 1 measurements, run with Docker Compose and tc netem
- [x] Scenarios in YAML

**Exit:** All policies run on the same trace; city-1-to-city-29 behaviour measurable. (PASSED)

## Phase 4: AWS integration (time-boxed to the lab window)

- [x] Deploy ingestion via IaC (CloudFormation in `infra/telemetry-pipeline.yaml`)
- [x] Cloud inference (Bedrock or EC2) behind the same client interface (`cloud/bedrock_client.py`)
- [x] Jetson outbox → authenticated outbound telemetry (`edge/telemetry_pusher.py`)
- [x] AWS capability check & report (`scripts/check_aws_capabilities.py`, `docs/aws-capability-report.md`)
- [x] Export everything before expiry (`scripts/export_before_expiry.sh`)

**Exit:** AWS path works, or documented fallback to the labelled mock. (PASSED)

## Phase 5: Dashboard and evaluation

- [x] FastAPI JSON and SSE endpoints (`gateway/app.py`); React dashboard with a "simulated vs measured" badge on every chart (`dashboard/`)
- [x] Panels: per-node energy, route taken, latency by policy, fairness view, outbox depth, cloud request count, locality rate
- [x] Run all scenarios, policies and repeats; ablations; outage and node-failure tests; quality evaluation (`scripts/run_evaluation_matrix.py`)

**Exit:** Tables and charts with honest write-up (`docs/results/evaluation-report.md`). (PASSED)

## Phase 6: Extensions (only after Phase 5)

Forecasting for the energy score; energy-price routing; real small solar panel with INA219 and battery on the Jetson; local-language model (Hindi, Marathi); peer-to-peer handoff; anomaly detection.
