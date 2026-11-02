# SunRoute — Standing Context

> Save this file as `CLAUDE.md` in the repo root. It provides standing context for Claude Code sessions.
> The build plan is in `docs/build-plan.md`.

## 1. Project in one paragraph

AI inference is concentrated in a few hyperscale data centers. This project prototypes a community-owned network of edge nodes (societies, parks, campuses) powered by local solar, wind and battery, cooperating with one central cloud tier. A query is routed to the best node by capacity, energy availability, locality and fairness, not first-come-first-served. The central data center stays as fallback and home of heavy models. The goal is democratised compute: ownership, fairness, resilience, local data control and use of clean energy. It is a research prototype, not a production system.

**Grocery analogy.** The data center is the mall (D-Mart). Edge nodes are neighbourhood kirana stores. The supply chain is the path of a query: routing, response return, telemetry, queueing and retries.

## 2. Scale we are designing for

A state with about 30 cities, hundreds to thousands of edge nodes, and one main data center in the capital. We cannot build that physically, so:

- **1 real node:** Jetson Orin Nano Super 8 GB (aarch64, L4T R39.2.1, JetPack 7.2).
- **Emulated nodes:** same edge-agent code, run as containers or simulated objects, always labelled `emulated`.
- **Large-scale study:** discrete-event simulation of 30 cities and 1,000+ nodes.
- **Cloud:** AWS lab account (temporary, about 24 hours, permission-limited).

## 3. Honest framing (rules for how we talk about results)

1. Big data-center GPUs are usually more energy-efficient per token than a small edge device. We do not claim edge saves energy per token. We measure it and report it either way.
2. The case for edge is ownership, fairness, resilience (offline operation), local data control, local-language service and use of local surplus renewable energy.
3. Define democracy metrics before building (Section 7) and report efficiency as one metric among them.
4. Every number is labelled `measured`, `simulated` or `estimated`, per column. Never mix them.
5. Report negative results. If cloud-only wins on an axis, say so.
6. Do not claim production readiness. Do not invent AWS capabilities: verify with the Phase 0 capability check.
7. Do not claim the idea is new without a literature check.

## 4. Research question and hypotheses

**RQ.** Can capacity-, energy- and locality-aware routing across community edge nodes and a cloud tier improve fairness, resilience and renewable use while keeping latency, quality and device limits within bounds?

| ID | Hypothesis | How it could fail |
|----|-----------|-------------------|
| H1 | Energy-aware routing raises the renewable share of inference energy versus cloud-only | Edge energy per token is much worse than cloud at batch |
| H2 | Routing short or simple prompts locally cuts p50 latency and cloud request count | Network is fast and Jetson tokens/s are slow |
| H3 | Capacity-aware scoring prevents battery depletion and overload that FCFS causes | Stale telemetry or scoring overhead causes bad decisions |
| H4 | During cloud or internet outage, edge keeps serving and recovers with 0 lost and 0 duplicate records | Outbox bugs, disk growth, clock issues |
| H5 | Edge answer quality stays acceptable on eligible task classes | Small quantised model too weak, so eligibility gate must tighten |
| H6 | Locality-aware routing keeps most queries in their home city and sends them farther only when local capacity or energy is short | Locality weight too strong starves remote capacity, or too weak causes needless long trips |
| H7 | A fairness mechanism keeps the worst-served node above a service floor without large latency cost | Fairness term hurts latency or is gamed |

**Baselines** (same seeded workload trace): cloud-only; edge-only; FCFS/round-robin; small-model-first cascade; the proposed router.

## 5. Architecture

### 5.1 Components and placement

| Place | Runs |
|-------|------|
| Jetson | Edge agent (FastAPI), llama.cpp server, deterministic energy rules, SQLite outbox, power probe |
| Laptop | Gateway and router, simulators, virtual nodes, API for dashboard, experiment runner |
| AWS | API Gateway → Lambda → SQS → Lambda (idempotent) → S3 and DynamoDB; Bedrock or EC2 inference; CloudWatch |
| Dashboard | React (Vite) calling a FastAPI JSON and SSE/WebSocket API |

### 5.2 Connections

- Client → gateway: local HTTPS with token.
- Gateway → Jetson: HTTPS over LAN, bearer token. Remote admin via Tailscale only.
- Gateway → virtual nodes: Docker network, with `tc netem` adding delay and loss to mimic distance.
- Gateway → cloud inference: HTTPS behind the same interface as an edge node.
- Jetson → AWS telemetry: outbound HTTPS only, from the outbox. Nothing calls into the Jetson from the internet.
- No AWS IAM keys on the Jetson. It holds only an API key or token allowed to post telemetry. Lab credentials stay on the laptop, outside the repo.

### 5.3 Hierarchy (so no component sees every node)

1. **Local:** nearest nodes in the same society or ward.
2. **City coordinator:** holds an aggregate of its nodes (spare capacity, mean battery, health), refreshed every few seconds.
3. **Regional:** neighbouring cities.
4. **State:** the capital data center as last fallback.

Inside a level, do not score all nodes. Use **power of two choices**: sample two eligible nodes and pick the better. A cache sits in front of inference.

### 5.4 Tech stack (decided)

| Part | Choice |
|------|--------|
| Edge agent, gateway, router | Python, FastAPI, pydantic |
| Inference runtime | llama.cpp server (build natively on Jetson first) |
| Local storage | SQLite (outbox on Jetson; decision log on gateway) |
| Experiment data | Parquet queried with DuckDB |
| Simulation | SimPy, NetworkX, pvlib (solar), windpowerlib (wind) |
| Cloud functions | Python Lambda, boto3 |
| Cloud data | DynamoDB (latest state, dedupe by message_id), S3 (raw) |
| IaC | CloudFormation or AWS CLI scripts in infra/ |
| Dashboard | React + Vite, Recharts or ECharts |
| Tests | pytest |
| Packaging | Docker and Docker Compose |

**Avoid:** Kubernetes, Kafka, Redis, Postgres/RDS, blockchain, AWS IoT Core (not assumed available). Add only if justified by data.

## 6. Routing design (the heart of the project)

The router is a pure function, unit-tested and swappable:

```python
route(request, node_states[], cloud_state, policy, origin) -> Decision(target, score_breakdown, reason)
```

### 6.1 Request

```json
{
  "request_id": "uuid",
  "created_at": "ISO-8601",
  "origin": {"city": "city-01", "site": "society-12"},
  "task_type": "classify | short_qa | summarize | chat | long_form",
  "prompt_tokens_est": 120,
  "max_output_tokens": 128,
  "latency_target_ms": 2000,
  "priority": "low | normal | high | essential",
  "privacy": "local_only | local_preferred | any",
  "min_quality_tier": "basic | standard | high"
}
```

### 6.2 Node state (reported every few seconds, validated)

```json
{
  "node_id": "jetson-01",
  "city": "city-01",
  "kind": "physical | emulated | cloud",
  "ts": "ISO-8601",
  "models": ["<model-name>"],
  "free_mem_mb": 3100,
  "gpu_util": 0.35,
  "queue_depth": 1,
  "temp_c": 58,
  "battery_soc": 0.72,
  "solar_w": 14.0,
  "wind_w": 3.5,
  "load_w": 9.2,
  "connectivity": "online | degraded | offline",
  "energy_source": "simulated | measured"
}
```

### 6.3 Routing steps

1. **Cache check:** answer from a local cache or FAQ if possible. No inference needed.
2. **Hard filters** (ineligible if any fail): model or task not supported; free memory too low; SOC below reserve floor (~20%) with no surplus generation; over thermal limit; queue over cap; telemetry stale (older than TTL) or unhealthy; quality tier too low; privacy = `local_only` and node is outside the allowed area.
3. **Escalate by level:** local → city → region → cloud. Cross-city only if nearer levels have no eligible node or priority demands it. Log the reason.
4. **Score eligible candidates** (all terms normalised 0–1, weights in YAML):
   ```
   score = w_e·energy + w_c·capacity + w_l·latency(incl. network RTT) + w_loc·locality
         + w_f·fairness − w_p·cloud_penalty
   ```
5. **Pick** with power of two choices inside a level.
6. **Admission control:** reserve estimated job energy (tokens × J/token from Jetson measurements) against projected SOC. The node's local rules have the final say and can veto, after which the router re-routes. Cloud suggestions are never executed without local validation.

**Fairness mechanism.** Each node keeps a plain ledger of compute contributed versus consumed (like net metering). Guarantees: a minimum service floor for every node, and priority for essential uses (health, education, emergency). No blockchain.

**Governance.** Routing weights and priority classes live in a versioned, public config. Every decision is written to an append-only audit log so anyone can see why a query went where it did.

**Optional research extension (only after baseline works).** Energy price per node: each node publishes one live price derived from battery, forecast and queue, and the router picks the cheapest eligible node. Compare it against the weighted score.

## 7. Metrics

| Category | Metrics |
|----------|--------|
| Democracy | Share of queries answered on community-owned nodes; Gini of service received; worst-served node; priority-class service rate; auditable decisions |
| Resilience | Hours served during outage; recovery time; duplicates (target 0); data loss (target 0) |
| Locality & privacy | Share of queries answered in home city; data-residency rate; cross-city rate vs local shortage |
| Energy | Jetson Wh/request and Wh/token (measured); renewable share (simulated or measured, labelled); cloud energy (estimate with stated source) |
| Latency & quality | p50/p95 end-to-end, TTFT, tokens/s; accuracy on labelled tasks; local-language coverage |
| Safety | Battery floor violations (target 0); thermal events; rejected requests |
| Cloud load | Cloud request count; tokens served by edge vs cloud |

**Method.** Identical seeded trace across all policies; at least 5 repeats per scenario; report medians and spread; fixed and recorded Jetson nvpmodel mode; warm-up excluded; ablations that remove each score term.

**Scenarios:** `sunny_day`, `cloudy_day`, `night_low_battery`, `windy_evening`, `internet_outage_30min`, `node_failure`, `city_blackout`, `traffic_spike`.

## 8. Repository layout

```
project-root/
├── CLAUDE.md                 # this context (Sections 1-8, 10)
├── README.md
├── docs/
│   ├── build-plan.md         # Section 9
│   ├── architecture.md
│   ├── routing-policy.md
│   ├── api-spec.md           # OpenAPI for edge + gateway
│   ├── aws-capability-report.md
│   ├── experiment-protocol.md
│   ├── security.md
│   ├── assumptions-and-limits.md
│   └── results/
├── edge/                     # Jetson agent, rules, outbox, power probe
├── router/                   # pure routing library, baselines, tests
├── gateway/                  # FastAPI gateway, decision log, dashboard API
├── simulator/                # energy, workload, topology, scenarios (YAML)
├── virtual_nodes/            # emulated nodes (Docker Compose, tc netem)
├── dashboard/                # React + Vite
├── cloud/                    # Lambda handlers, inference client, mock cloud
├── infra/                    # CloudFormation / CLI scripts
├── experiments/              # runner, configs, raw logs, analysis
└── scripts/                  # setup, benchmarks, export-before-expiry
```

## 10. Rules for Claude Code (standing instructions)

1. Work in small steps. One component per session. Run the tests before moving on.
2. Tests first for the router, energy rules and outbox. Cover edge cases: all nodes ineligible, stale telemetry, SOC at the floor, duplicate message_id.
3. Pure functions for routing. No network or clock calls inside `route()`; inject them.
4. Config, not code: weights, thresholds and scenarios in YAML.
5. Label data: every metric carries `measured`, `simulated` or `estimated`.
6. Security: no secrets in the repo; TLS and tokens; schema validation; no public SSH or dashboards; local policy has the final say.
7. Never invent: do not assume AWS permissions, model availability or hardware numbers. Ask or check.
8. Keep it simple: no Kubernetes, Kafka, Redis or Postgres without a written justification in `docs/`.
9. Explain decisions in `docs/` as you go, so the final report writes itself.
10. Ask when blocked instead of guessing. Report what you could not verify.
