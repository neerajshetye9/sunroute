"""Deterministic energy rules and admission control for SunRoute edge nodes.

Enforces reserve SOC, critical SOC, thermal limits, surplus generation detection,
and estimated job energy reservation per CLAUDE.md Section 6.3.
"""

from __future__ import annotations

from dataclasses import dataclass

from edge.schemas import InferenceRequest, NodeState, Priority


@dataclass(frozen=True)
class EnergyRulesConfig:
    reserve_soc: float = 0.20  # Below this, only essential or surplus-powered queries
    critical_soc: float = 0.10  # Below this, hard shutdown: all queries vetoed
    thermal_limit_c: float = 80.0  # Maximum operating temperature in Celsius
    surplus_threshold_w: float = 2.0  # Generation must exceed load by this to count as surplus
    joules_per_token_est: float = 0.15  # Default estimated J/token on Orin Nano
    battery_capacity_wh: float = 50.0  # Nominal battery capacity in Wh (e.g., 50Wh / 180kJ)


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    reason: str
    projected_soc: float
    surplus_active: bool
    estimated_energy_j: float


def check_surplus_generation(state: NodeState, threshold_w: float = 2.0) -> bool:
    """Check if renewable generation exceeds current load by at least threshold_w."""
    total_gen_w = state.solar_w + state.wind_w
    return total_gen_w > (state.load_w + threshold_w)


def estimate_job_energy(
    prompt_tokens: int,
    max_output_tokens: int,
    joules_per_token: float,
) -> float:
    """Calculate projected energy needed for the inference job in Joules."""
    total_tokens = prompt_tokens + max_output_tokens
    return total_tokens * joules_per_token


def calculate_projected_soc(
    current_soc: float,
    energy_j: float,
    battery_capacity_wh: float,
) -> float:
    """Calculate new SOC after consuming energy_j (1 Wh = 3600 Joules)."""
    battery_capacity_j = battery_capacity_wh * 3600.0
    if battery_capacity_j <= 0.0:
        return current_soc
    delta_soc = energy_j / battery_capacity_j
    return max(0.0, current_soc - delta_soc)


def evaluate_admission(
    request: InferenceRequest,
    state: NodeState,
    config: EnergyRulesConfig | None = None,
) -> AdmissionDecision:
    """Pure, deterministic evaluation of query admission against node energy rules.

    Local rules have final say and can veto router suggestions.
    """
    cfg = config or EnergyRulesConfig()

    # 1. Thermal Safety Check (Absolute Hard Cutoff)
    if state.temp_c >= cfg.thermal_limit_c:
        return AdmissionDecision(
            admitted=False,
            reason=f"Thermal limit exceeded ({state.temp_c:.1f}°C >= {cfg.thermal_limit_c:.1f}°C)",
            projected_soc=state.battery_soc,
            surplus_active=False,
            estimated_energy_j=0.0,
        )

    # 2. Critical Battery SOC Cutoff (Hard Shutdown)
    if state.battery_soc <= cfg.critical_soc:
        soc_pct = state.battery_soc * 100.0
        crit_pct = cfg.critical_soc * 100.0
        return AdmissionDecision(
            admitted=False,
            reason=f"Battery critically low ({soc_pct:.1f}% <= {crit_pct:.1f}%)",
            projected_soc=state.battery_soc,
            surplus_active=False,
            estimated_energy_j=0.0,
        )

    # 3. Surplus Renewable Generation Check
    has_surplus = check_surplus_generation(state, cfg.surplus_threshold_w)

    # 4. Energy Reservation and Projected SOC
    est_energy_j = estimate_job_energy(
        request.prompt_tokens_est,
        request.max_output_tokens,
        cfg.joules_per_token_est,
    )
    proj_soc = calculate_projected_soc(state.battery_soc, est_energy_j, cfg.battery_capacity_wh)

    # 5. Reserve SOC Floor Evaluation
    # If battery is below reserve floor (or will breach reserve floor):
    # - Admitted if renewable generation has active surplus
    # - Admitted if query priority is ESSENTIAL (health/education/emergency)
    # - Otherwise vetoed
    is_at_reserve = state.battery_soc < cfg.reserve_soc or proj_soc < cfg.reserve_soc
    if is_at_reserve and not has_surplus and request.priority != Priority.ESSENTIAL:
        soc_pct = state.battery_soc * 100.0
        res_pct = cfg.reserve_soc * 100.0
        return AdmissionDecision(
            admitted=False,
            reason=(
                f"Battery at reserve floor ({soc_pct:.1f}% < {res_pct:.1f}%) "
                "with no surplus generation and non-essential priority"
            ),
            projected_soc=proj_soc,
            surplus_active=has_surplus,
            estimated_energy_j=est_energy_j,
        )

    # 6. Admitted
    reason = (
        "Admitted: surplus renewable power available"
        if has_surplus
        else "Admitted: battery SOC within safe operational bounds"
    )
    return AdmissionDecision(
        admitted=True,
        reason=reason,
        projected_soc=proj_soc,
        surplus_active=has_surplus,
        estimated_energy_j=est_energy_j,
    )
