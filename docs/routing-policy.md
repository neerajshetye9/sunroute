# SunRoute Routing Policy & Algorithm Specification

The SunRoute router is a **pure function** without external side-effects, network calls, or non-deterministic clock evaluations:

$$\text{route}(\text{request}, \text{node\_states}[], \text{cloud\_state}, \text{policy}, \text{origin}) \to \text{Decision}$$

---

## 1. Routing Steps

1. **Cache Check**: If an identical prompt or FAQ answer exists in local cache, query returns immediately without inference.
2. **Hard Filters**: Ineligible nodes are eliminated before scoring.
3. **Hierarchy Escalation**:
   - `local`: Nearest nodes in the origin site/society.
   - `city`: City coordinator level nodes.
   - `region`: Neighbouring cities.
   - `cloud`: Central fallback data center.
4. **Power of Two Choices**: Inside each eligible level, 2 nodes are sampled at random and scored. The higher-scoring node is selected.
5. **Admission Control**: Local energy rules on the node reserve estimated energy ($\Delta \text{SOC}$) with final veto power.

---

## 2. Hard Filters

A node is marked ineligible if any of the following conditions fail:
- **Connectivity**: Node is `offline`.
- **Telemetry Freshness**: Telemetry older than TTL ($\Delta t > 30\text{s}$).
- **Thermal Safety**: SoC temperature $\ge 80^\circ\text{C}$.
- **Memory**: Free RAM $< 500\text{ MB}$.
- **Capacity**: Queue depth $\ge \text{max\_queue\_depth}$ (10) or GPU utilization $> 95\%$.
- **Critical Battery Floor**: $\text{SOC} \le 10\%$.
- **Reserve Battery Floor**: $\text{SOC} < 20\%$, unless renewable surplus generation is present or request is `ESSENTIAL`.
- **Privacy Constraints**: If `privacy = local_only`, remote cities and cloud nodes are strictly excluded.

---

## 3. Scoring Function

For eligible candidates, normalized terms ($[0.0, 1.0]$) are calculated:

$$\text{Score} = w_e \cdot \text{energy} + w_c \cdot \text{capacity} + w_l \cdot \text{latency} + w_{loc} \cdot \text{locality} + w_f \cdot \text{fairness} - w_p \cdot \text{cloud\_penalty}$$

### Term Definitions:
1. **Energy** ($w_e = 0.25$): $\min(1.0, \text{SOC} + \text{surplus\_bonus})$. Grid cloud defaults to $0.20$.
2. **Capacity** ($w_c = 0.20$): Spare queue headroom, free RAM, and GPU idle capacity.
3. **Latency** ($w_l = 0.20$): Estimated round-trip latency ($\text{RTT}_{\text{tier}} + t_{\text{inference}}$) vs request budget.
4. **Locality** ($w_{loc} = 0.15$): $1.0$ (local), $0.8$ (same city), $0.4$ (regional), $0.0$ (cloud).
5. **Fairness** ($w_f = 0.10$): Net compute ledger balance ($\text{contributed} - \text{consumed}$).
6. **Cloud Penalty** ($w_p = 0.10$): $1.0$ for central cloud, $0.0$ for edge.

---

## 4. Baselines

- **`cloud_only`**: Always dispatches to central AWS / data-center tier.
- **`edge_only`**: Strict community edge execution; rejects if no edge node is eligible.
- **`fcfs`**: First-come-first-served; selects first eligible node without multi-objective scoring.
- **`cascade`**: Small-model-first cascade; simple queries route to edge, complex/long queries escalate to cloud.
- **`proposed`**: Hierarchical multi-objective routing with power of two choices.
