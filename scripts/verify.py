from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
NODE = shutil.which("node") or "node"
SH = shutil.which("sh") or "sh"


def run_command(label: str, command: Sequence[str], *, cwd: Path = ROOT) -> None:
    print(f"\n== {label} ==", flush=True)
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run(list(command), cwd=cwd, check=True)


def typecheck() -> None:
    run_command(
        "TypeScript typecheck",
        [NODE, "node_modules/typescript/bin/tsc", "-b", "tsconfig.json", "--pretty", "false"],
        cwd=FRONTEND,
    )


def lint() -> None:
    run_command("ESLint", [NODE, "node_modules/eslint/bin/eslint.js", "."], cwd=FRONTEND)


def frontend_unit() -> None:
    run_command(
        "Frontend unit tests compile",
        [NODE, "node_modules/typescript/bin/tsc", "-p", "tsconfig.unit.json"],
        cwd=FRONTEND,
    )
    test_files = sorted((FRONTEND / ".unit-test-dist" / "tests" / "unit").glob("*.test.js"))
    if not test_files:
        raise RuntimeError("Frontend unit tests: no compiled test files found")
    run_command(
        "Frontend unit tests",
        [NODE, "--test", *(str(path) for path in test_files)],
        cwd=FRONTEND,
    )


def python_unit() -> None:
    run_command(
        "Python unit tests",
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
    )


def frontend_e2e() -> None:
    run_command(
        "Frontend browser tests",
        [NODE, "node_modules/@playwright/test/cli.js", "test"],
        cwd=FRONTEND,
    )


def public_build() -> None:
    run_command("Public build", [SH, "scripts/build_public.sh"])


def public_build_validation() -> None:
    run_command("Public build validation", [sys.executable, "scripts/check_public_build.py"])


def public_reproducibility() -> None:
    run_command("Public reproducibility", [sys.executable, "scripts/check_public_reproducibility.py"])


def public_e2e() -> None:
    run_command(
        "Public browser tests",
        [NODE, "node_modules/@playwright/test/cli.js", "test", "--config=playwright.public.config.js"],
    )


def repository_hygiene() -> None:
    run_command("Repository hygiene", [sys.executable, "scripts/check_repository_hygiene.py"])


def live_twitch() -> None:
    run_command(
        "Live Twitch tests",
        [NODE, "node_modules/@playwright/test/cli.js", "test", "--config=playwright.twitch.config.js"],
    )


def live_production() -> None:
    run_command(
        "Deployed production tests",
        [NODE, "node_modules/@playwright/test/cli.js", "test", "--config=playwright.live.config.js"],
    )


def live_data() -> None:
    run_command("Deployed data validation", [sys.executable, "scripts/verify_deployed_data.py"])


STEPS: dict[str, Callable[[], None]] = {
    "typecheck": typecheck,
    "lint": lint,
    "frontend-unit": frontend_unit,
    "python": python_unit,
    "frontend-e2e": frontend_e2e,
    "public-build": public_build,
    "public-build-validation": public_build_validation,
    "public-reproducibility": public_reproducibility,
    "public-e2e": public_e2e,
    "hygiene": repository_hygiene,
    "live-twitch": live_twitch,
    "live-production": live_production,
    "live-data": live_data,
}
STANDARD_SEQUENCE = (
    "typecheck",
    "lint",
    "frontend-unit",
    "python",
    "frontend-e2e",
    "public-build",
    "public-build-validation",
    "public-reproducibility",
    "public-e2e",
    "hygiene",
)
GROUPS = {
    "all": STANDARD_SEQUENCE,
    "public-checks": ("public-build-validation", "public-reproducibility"),
    "live": ("live-twitch", "live-production", "live-data"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the canonical repository verification without nested npm scripts.")
    parser.add_argument("--step", choices=sorted((*STEPS, *GROUPS)), default="all")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = GROUPS.get(args.step, (args.step,))
    try:
        for step_name in selected:
            STEPS[step_name]()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1
    print("\nverification passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
