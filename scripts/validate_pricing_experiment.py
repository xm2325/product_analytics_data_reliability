from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import statsmodels.api as sm
from scipy.stats import binomtest, norm


def _fail(message: str) -> None:
    raise SystemExit(f"Pricing-experiment validation failed: {message}")


def _assert_close(actual: float, expected: float, label: str, tol: float = 1e-10) -> None:
    if abs(float(actual) - float(expected)) > tol:
        _fail(f"{label}: expected {expected}, got {actual}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: validate_pricing_experiment.py <build-dir>")
    root = Path(sys.argv[1])

    users = pd.read_csv(root / "pricing_experiment_users.csv")
    estimates = pd.read_csv(root / "pricing_experiment_estimates.csv")
    contract = json.loads((root / "pricing_experiment_contract.json").read_text(encoding="utf-8"))
    decision_payload = json.loads((root / "pricing_experiment_decision.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "reference_summary.json").read_text(encoding="utf-8"))

    required_user_columns = {
        "experiment_user_id",
        "treatment",
        "pre_revenue_gbp_30d",
        "revenue_gbp_30d",
        "paid_subscription_30d",
    }
    if set(users.columns) != required_user_columns:
        _fail(f"unexpected user columns: {list(users.columns)}")
    if len(users) != 8000 or users["experiment_user_id"].nunique() != 8000:
        _fail("reference must contain 8,000 unique experiment users")
    if set(users["treatment"].unique()) != {0, 1}:
        _fail("treatment must be binary 0/1")
    n_treatment = int(users["treatment"].sum())
    n_control = int(len(users) - n_treatment)
    if (n_control, n_treatment) != (4000, 4000):
        _fail(f"expected exact 4,000/4,000 allocation, got {n_control}/{n_treatment}")

    srm_p = float(binomtest(n_treatment, len(users), p=0.5, alternative="two-sided").pvalue)
    integrity = decision_payload["integrity"]
    _assert_close(integrity["p_value"], srm_p, "SRM p-value")
    if integrity["alpha"] != 0.001 or not integrity["passes"]:
        _fail("assignment-integrity contract must pass at alpha=0.001")

    design = pd.DataFrame(
        {
            "treatment": users["treatment"].astype(float),
            "pre_period": users["pre_revenue_gbp_30d"].astype(float),
        }
    )
    revenue_fit = sm.OLS(
        users["revenue_gbp_30d"].astype(float),
        sm.add_constant(design, has_constant="add"),
    ).fit(cov_type="HC3")
    z = float(norm.ppf(0.975))
    revenue_effect = float(revenue_fit.params["treatment"])
    revenue_se = float(revenue_fit.bse["treatment"])
    revenue_low = revenue_effect - z * revenue_se
    revenue_high = revenue_effect + z * revenue_se

    control_paid = users.loc[users["treatment"].eq(0), "paid_subscription_30d"].astype(float)
    treatment_paid = users.loc[users["treatment"].eq(1), "paid_subscription_30d"].astype(float)
    paid_effect = float(treatment_paid.mean() - control_paid.mean())
    paid_se = float(
        (
            treatment_paid.var(ddof=1) / len(treatment_paid)
            + control_paid.var(ddof=1) / len(control_paid)
        )
        ** 0.5
    )
    paid_low = paid_effect - z * paid_se
    paid_high = paid_effect + z * paid_se

    revenue_row = estimates.loc[estimates["metric"].eq("revenue_gbp_30d")]
    paid_row = estimates.loc[estimates["metric"].eq("paid_subscription_30d")]
    if len(revenue_row) != 1 or len(paid_row) != 1:
        _fail("estimate table must contain exactly one row per declared metric")
    revenue_row = revenue_row.iloc[0]
    paid_row = paid_row.iloc[0]
    for field, expected in {
        "effect": revenue_effect,
        "se": revenue_se,
        "ci_low": revenue_low,
        "ci_high": revenue_high,
    }.items():
        _assert_close(revenue_row[field], expected, f"revenue {field}")
    for field, expected in {
        "effect": paid_effect,
        "se": paid_se,
        "ci_low": paid_low,
        "ci_high": paid_high,
    }.items():
        _assert_close(paid_row[field], expected, f"paid {field}")

    if contract.get("weighted_score_used") is not False:
        _fail("weighted score must remain disabled")
    if contract.get("revenue_cannot_compensate_for_guardrail_failure") is not True:
        _fail("non-compensatory guardrail contract is missing")
    if float(contract.get("paid_harm_guardrail")) != -0.03:
        _fail("paid-conversion harm guardrail must remain -0.03")

    decision = decision_payload["decision"]
    if decision["action"] != "hold":
        _fail(f"reference decision must HOLD, got {decision['action']}")
    if not decision["assignment_integrity_gate"] or not decision["revenue_gate"]:
        _fail("reference must pass assignment-integrity and revenue gates")
    if decision["paid_guardrail_gate"]:
        _fail("reference paid-conversion guardrail must fail")
    if not (paid_effect > -0.03 and paid_low < -0.03):
        _fail("reference must demonstrate point estimate inside margin but lower CI crossing margin")
    if revenue_low <= 0:
        _fail("reference revenue lower confidence bound must be positive")

    reference = summary.get("pricing_experiment")
    if not reference:
        _fail("reference_summary.json is missing pricing_experiment")
    if reference["decision"] != decision:
        _fail("summary decision differs from decision artifact")
    if reference["integrity"] != integrity:
        _fail("summary integrity differs from decision artifact")

    # Pinned reference evidence: changes require an explicit public-claim review.
    _assert_close(revenue_effect, 0.6850808285539077, "pinned revenue effect", tol=1e-9)
    _assert_close(revenue_low, 0.5514297450276839, "pinned revenue lower CI", tol=1e-9)
    _assert_close(paid_effect, -0.01625, "pinned paid effect", tol=1e-12)
    _assert_close(paid_low, -0.03363352022846357, "pinned paid lower CI", tol=1e-9)

    print(f"Pricing-experiment validation passed: {root}")


if __name__ == "__main__":
    main()
