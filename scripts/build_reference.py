from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from upgrade_contract_reference import upgrade_contract_reference
from upgrade_forecast_reference import upgrade_forecast_reference


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the complete v0.35 synthetic reference evidence bundle")
    parser.add_argument("--output-dir", default="build/reference")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--seed", type=int, default=2206)
    args = parser.parse_args()

    root = Path(args.output_dir)
    subprocess.run(
        [
            sys.executable,
            "scripts/run_workbench.py",
            "--output-dir",
            str(root),
            "--days",
            str(args.days),
            "--seed",
            str(args.seed),
        ],
        check=True,
    )
    forecast = upgrade_forecast_reference(root)
    migration = upgrade_contract_reference(root)
    print(
        "v0.35 reference complete: "
        f"{forecast['approved']} forecast metrics approved, "
        f"{forecast['withheld']} withheld; "
        f"migration actions={migration['actions']}; "
        f"{migration['manifest_artifacts']} portable artifacts"
    )


if __name__ == "__main__":
    main()
