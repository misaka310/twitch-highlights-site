from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path


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


FORBIDDEN_LOCAL_PATHS = (
    Path("="),
    Path("frontend") / "=",
)

PERSONAL_PATH_PATTERN = re.compile(r"(?i)[A-Z]:[\\/](?:Users|00_doc|00_dev)[\\/]")
REMOTE_HOME_PATH_PATTERN = re.compile(r"(?i)(?:^|[^$A-Z])/" + "home/" + r"[^/\s`\"']+")
PUBLIC_IPV4_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


def find_local_output_violations(root: Path = Path(".")) -> list[str]:
    violations: list[str] = []
    for relative_path in FORBIDDEN_LOCAL_PATHS:
        if (root / relative_path).exists():
            normalized = relative_path.as_posix()
            violations.append(f"{normalized}: accidental npm cache argument directory must be removed")
    return violations


def tracked_paths(root: Path = Path(".")) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [path.decode("utf-8") for path in result.stdout.split(b"\0") if path]


def find_public_disclosure_violations(root: Path = Path(".")) -> list[str]:
    violations: list[str] = []
    for relative_path in tracked_paths(root):
        path = root / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if PERSONAL_PATH_PATTERN.search(text) or REMOTE_HOME_PATH_PATTERN.search(text):
            violations.append(f"{relative_path}: machine-specific path must not be tracked")
            continue
        if any(
            not match.group(0).startswith(("127.", "0."))
            for match in PUBLIC_IPV4_PATTERN.finditer(text)
        ):
            violations.append(f"{relative_path}: public IP address literal must not be tracked")
    return violations


def main() -> int:
    violations = find_local_output_violations()
    violations.extend(find_public_disclosure_violations())
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
    print("- machine-specific paths and public IP literals are absent from tracked text")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
