from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Iterable


@dataclass(frozen=True)
class RiskBudget:
    max_es95_gbp_per_1000: float = 1700.0
    max_unsafe_exposure_per_1000: float = 5.0
    max_tail_concentration: float = 0.60
    max_readout_days: float = 365.0


@dataclass(frozen=True)
class DesignCandidate:
    treatment_share: float
    balanced_equivalent_information: int
    total_users: int
    treatment_users: int
    control_users: int
    readout_days: float
    es95_gbp_per_1000: float
    unsafe_exposure_per_1000: float
    tail_concentration: float

    def passes(self, budget: RiskBudget = RiskBudget()) -> bool:
        return (
            self.es95_gbp_per_1000 <= budget.max_es95_gbp_per_1000
            and self.unsafe_exposure_per_1000 <= budget.max_unsafe_exposure_per_1000
            and self.tail_concentration <= budget.max_tail_concentration
            and self.readout_days <= budget.max_readout_days
        )


def total_n_for_balanced_equivalent_information(info_n: int, treatment_share: float) -> int:
    """Total N needed to match balanced information under equal arm variance.

    For total N and treatment share p, balanced-equivalent information is
    approximately 4*N*p*(1-p).
    """
    p = float(treatment_share)
    if not 0 < p < 1:
        raise ValueError("treatment_share must be between 0 and 1")
    return int(ceil(float(info_n) / (4.0 * p * (1.0 - p))))


def allocation_counts(info_n: int, treatment_share: float) -> tuple[int, int, int]:
    total = total_n_for_balanced_equivalent_information(info_n, treatment_share)
    treated = int(round(total * treatment_share))
    control = total - treated
    return total, treated, control


def select_design(candidates: Iterable[DesignCandidate], budget: RiskBudget = RiskBudget()) -> DesignCandidate:
    """Safety-first lexicographic selection among already evaluated designs."""
    feasible = [candidate for candidate in candidates if candidate.passes(budget)]
    if not feasible:
        raise ValueError("No candidate satisfies all declared constraints")
    return min(feasible, key=lambda x: (x.treatment_users, x.readout_days, x.total_users))


def variance_adjusted_information(
    control_n: int,
    treatment_n: int,
    treatment_sd_ratio: float = 1.0,
) -> float:
    """Balanced-equivalent information when treatment SD differs from control.

    The scale assumes control variance = 1 and treatment variance = ratio^2.
    """
    if control_n <= 0 or treatment_n <= 0 or treatment_sd_ratio <= 0:
        raise ValueError("Counts and SD ratio must be positive")
    return 4.0 / (1.0 / control_n + treatment_sd_ratio**2 / treatment_n)
