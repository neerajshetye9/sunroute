# Build Plan

> This is the step-by-step build plan (Section 9 of the project specification).
> Each phase has exit checks that must pass before moving to the next.

## Phase 0: Foundation

- [ ] git init, repo layout, .gitignore (secrets, models, logs), pre-commit secrets scan
- [ ] Jetson: verify JetPack, CUDA and nvpmodel mode; install jtop; record idle power
- [ ] Build llama.cpp natively on the Jetson with CUDA for the Orin architecture (sm_87). JetPack 7.2 is new, so third-party containers may lag. Check whether jetson-containers supports it before depending on it
- [ ] Python environment with pinned dependencies
- [ ] AWS capability check script and report (run as soon as the lab opens)
- [ ] Write docs/assumptions-and-limits.md

**Exit:** Jetson answers a prompt locally; idle and load power recorded.

## Phase 1: Measure first

- [ ] Benchmark 2–3 quantised models of about 1–3 B parameters: tokens/s, TTFT, RAM, watts, joules/token
- [ ] Measure the same for the cloud model when available
- [ ] Pick one model for the edge by speed versus quality

**Exit:** Results table with `measured` labels. These numbers calibrate everything else.

## Phase 2: Core software (no AWS needed)

- [ ] OpenAPI spec for edge and gateway
- [ ] Edge agent: `/infer`, `/state`, `/health`, auth, validation, rate and size limits
- [ ] Deterministic energy rules plus unit tests
- [ ] SQLite outbox: retry with backoff and jitter, expiry, idempotency, failure-injection tests
- [ ] Router library: hard filters, scoring, locality, fairness ledger, power of two choices, baselines (cloud-only, FCFS, cascade), unit tests
- [ ] Mock cloud with the same interface as the AWS client
- [ ] Gateway with append-only decision log

**Exit:** Full local loop runs end to end on one command.

## Phase 3: Simulation at scale

- [ ] Energy simulator (solar via pvlib, wind via Weibull and power curve, battery SOC, demand with bursts), seeded
- [ ] SimPy topology: 30 cities, hundreds to thousands of nodes, hierarchy, latency matrix
- [ ] Virtual nodes calibrated from Phase 1 measurements, run with Docker Compose and tc netem
- [ ] Scenarios in YAML

**Exit:** All policies run on the same trace; city-1-to-city-29 behaviour measurable.

## Phase 4: AWS integration (time-boxed to the lab window)

- [ ] Deploy ingestion via IaC
- [ ] Cloud inference (Bedrock or EC2) behind the same client interface
- [ ] Jetson outbox → authenticated outbound telemetry
- [ ] Rerun key experiments against real latency
- [ ] Export everything before expiry (templates, logs, S3, DynamoDB, results)

**Exit:** AWS path works, or documented fallback to the labelled mock.

## Phase 5: Dashboard and evaluation

- [ ] FastAPI JSON and SSE endpoints; React dashboard with a "simulated vs measured" badge on every chart
- [ ] Panels: per-node energy, route taken, latency by policy, fairness view, outbox depth, cloud request count, locality rate
- [ ] Run all scenarios, policies and repeats; ablations; outage and node-failure tests; quality evaluation

**Exit:** Tables and charts with honest write-up.

## Phase 6: Extensions (only after Phase 5)

Forecasting for the energy score; energy-price routing; real small solar panel with INA219 and battery on the Jetson; local-language model (Hindi, Marathi); peer-to-peer handoff; anomaly detection.
