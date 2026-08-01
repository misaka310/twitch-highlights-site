from __future__ import annotations

import fnmatch
import subprocess
import sys


FORBIDDEN_EXACT = {
    "headline-diagnostics.txt",
    "headline-diagnostics-summary.txt",
    "headline-generation.log",
}

FORBIDDEN_PREFIXES = (
    ".ai-bridge/",
    ".ai-review/",
    "artifacts/",
    "test-results/",
)

FORBIDDEN_GLOBS = (
    "headline-diagnostics*.txt",
    ".github/workflows/*one-time*.yml",
    ".github/workflows/*one-time*.yaml",
    ".github/workflows/*temporary*.yml",
    ".github/workflows/*temporary*.yaml",
    ".github/workflows/*applicator*.yml",
    ".github/workflows/*applicator*.yaml",
)


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [path.decode("utf-8") for path in result.stdout.split(b"\0") if path]


def main() -> int:
    violations: list[str] = []
    for path in tracked_paths():
        normalized = path.replace("\\", "/")
        if normalized in FORBIDDEN_EXACT:
            violations.append(f"{normalized}: generated diagnostic output must be an Actions artifact, not a commit")
            continue
        if normalized.startswith(FORBIDDEN_PREFIXES):
            violations.append(f"{normalized}: local or generated output must not be tracked")
            continue
        if any(fnmatch.fnmatch(normalized, pattern) for pattern in FORBIDDEN_GLOBS):
            violations.append(f"{normalized}: temporary mutation workflows and diagnostic summaries are not public source")

    if violations:
        print("REPOSITORY HYGIENE: FAIL", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1

    print("REPOSITORY HYGIENE: PASS")
    print("- generated diagnostics remain ephemeral Actions artifacts")
    print("- temporary mutation workflows are not tracked")
    print("- local agent and test output is absent from the public tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
