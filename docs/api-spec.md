# SunRoute OpenAPI 3.1 Specification

This document defines the REST APIs for the **Edge Agent** (running on Jetson or virtual nodes) and the **Gateway** (running on the coordinator tier).

---

## 1. Edge Agent API

The Edge Agent exposes local inference, telemetry reporting, and health monitoring endpoints. All mutating/inference endpoints are protected by Bearer Token Authentication.

```yaml
openapi: 3.1.0
info:
  title: SunRoute Edge Agent API
  version: 0.1.0
  description: >
    Edge node agent for democratised inference, telemetry publishing,
    and deterministic local admission control.
servers:
  - url: http://localhost:8001
    description: Local Jetson or Virtual Node Agent

components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT / Token
      description: Pre-shared token configured via EDGE_API_TOKEN.

  schemas:
    TaskType:
      type: string
      enum: [classify, short_qa, summarize, chat, long_form]

    Priority:
      type: string
      enum: [low, normal, high, essential]

    Privacy:
      type: string
      enum: [local_only, local_preferred, any]

    QualityTier:
      type: string
      enum: [basic, standard, high]

    NodeKind:
      type: string
      enum: [physical, emulated, cloud]

    ConnectivityStatus:
      type: string
      enum: [online, degraded, offline]

    EnergySource:
      type: string
      enum: [simulated, measured]

    Origin:
      type: object
      required: [city, site]
      properties:
        city:
          type: string
          example: city-01
        site:
          type: string
          example: society-12

    InferenceRequest:
      type: object
      required:
        - request_id
        - created_at
        - origin
        - task_type
        - prompt_tokens_est
        - max_output_tokens
        - latency_target_ms
        - priority
        - privacy
        - min_quality_tier
        - prompt
      properties:
        request_id:
          type: string
          format: uuid
          example: "550e8400-e29b-41d4-a716-446655440000"
        created_at:
          type: string
          format: date-time
          example: "2026-11-02T12:00:00Z"
        origin:
          $ref: '#/components/schemas/Origin'
        task_type:
          $ref: '#/components/schemas/TaskType'
        prompt_tokens_est:
          type: integer
          minimum: 1
          maximum: 2048
          example: 120
        max_output_tokens:
          type: integer
          minimum: 1
          maximum: 1024
          example: 128
        latency_target_ms:
          type: integer
          minimum: 50
          maximum: 60000
          example: 2000
        priority:
          $ref: '#/components/schemas/Priority'
        privacy:
          $ref: '#/components/schemas/Privacy'
        min_quality_tier:
          $ref: '#/components/schemas/QualityTier'
        prompt:
          type: string
          maxLength: 8192
          example: "Summarise local solar generation principles."

    InferenceResponse:
      type: object
      required:
        - request_id
        - node_id
        - text
        - prompt_tokens
        - output_tokens
        - latency_ms
        - energy_consumed_j_est
      properties:
        request_id:
          type: string
          format: uuid
        node_id:
          type: string
          example: "jetson-01"
        text:
          type: string
          example: "Solar generation converts sunlight to electrical power..."
        prompt_tokens:
          type: integer
          example: 120
        output_tokens:
          type: integer
          example: 64
        latency_ms:
          type: number
          example: 850.5
        energy_consumed_j_est:
          type: number
          example: 12.4

    NodeState:
      type: object
      required:
        - node_id
        - city
        - kind
        - ts
        - models
        - free_mem_mb
        - gpu_util
        - queue_depth
        - temp_c
        - battery_soc
        - solar_w
        - wind_w
        - load_w
        - connectivity
        - energy_source
      properties:
        node_id:
          type: string
          example: "jetson-01"
        city:
          type: string
          example: "city-01"
        kind:
          $ref: '#/components/schemas/NodeKind'
        ts:
          type: string
          format: date-time
        models:
          type: array
          items:
            type: string
          example: ["qwen2.5-1.5b-instruct-q4_k_m"]
        free_mem_mb:
          type: number
          minimum: 0
          example: 3100.0
        gpu_util:
          type: number
          minimum: 0.0
          maximum: 1.0
          example: 0.35
        queue_depth:
          type: integer
          minimum: 0
          example: 1
        temp_c:
          type: number
          example: 58.0
        battery_soc:
          type: number
          minimum: 0.0
          maximum: 1.0
          example: 0.72
        solar_w:
          type: number
          minimum: 0.0
          example: 14.0
        wind_w:
          type: number
          minimum: 0.0
          example: 3.5
        load_w:
          type: number
          minimum: 0.0
          example: 9.2
        connectivity:
          $ref: '#/components/schemas/ConnectivityStatus'
        energy_source:
          $ref: '#/components/schemas/EnergySource'

    HealthResponse:
      type: object
      required:
        - status
        - node_id
        - runtime_backend
        - uptime_s
        - queue_depth
      properties:
        status:
          type: string
          enum: [healthy, degraded, unhealthy]
          example: "healthy"
        node_id:
          type: string
          example: "jetson-01"
        runtime_backend:
          type: string
          example: "llama.cpp"
        uptime_s:
          type: number
          example: 1450.2
        queue_depth:
          type: integer
          example: 0

paths:
  /infer:
    post:
      summary: Execute edge model inference
      security:
        - BearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/InferenceRequest'
      responses:
        '200':
          description: Inference completed successfully
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/InferenceResponse'
        '400':
          description: Validation error or payload too large
        '401':
          description: Unauthorized (missing or invalid Bearer token)
        '429':
          description: Rate limit or queue depth limit exceeded
        '503':
          description: Node unavailable (thermal cutoff or critical battery SOC)

  /state:
    get:
      summary: Retrieve current node telemetry and resource state
      responses:
        '200':
          description: Node state snapshot
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NodeState'

  /health:
    get:
      summary: Node liveness and readiness probe
      responses:
        '200':
          description: Health check result
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HealthResponse'
```

---

## 2. Gateway API

The Gateway is the centralized ingress router. It ingests client inference queries, invokes the routing algorithm, routes requests to edge nodes or cloud fallbacks, and serves decision audit telemetry to dashboards.

```yaml
openapi: 3.1.0
info:
  title: SunRoute Gateway API
  version: 0.1.0
  description: >
    Entrypoint router directing requests across community edge nodes and cloud
    fallback tiers based on capacity, energy, locality, and fairness.
servers:
  - url: http://localhost:8000
    description: Local Coordinator Gateway

paths:
  /v1/chat/completions:
    post:
      summary: Route and dispatch inference request
      security:
        - BearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/InferenceRequest'
      responses:
        '200':
          description: Inference result with routing decision metadata
        '503':
          description: All tiers exhausted or rejected

  /v1/telemetry/nodes:
    get:
      summary: Get live telemetry state from all registered nodes
      responses:
        '200':
          description: Array of NodeState objects

  /v1/decisions:
    get:
      summary: Query recent routing decisions from append-only audit log
      parameters:
        - name: limit
          in: query
          schema:
            type: integer
            default: 100
      responses:
        '200':
          description: List of audit records with score breakdowns
```
