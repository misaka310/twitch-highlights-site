#!/usr/bin/env python3
"""Copy or verify the public runtime against an explicit source repository."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_files(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
    }


def compare(source: Path, target: Path) -> list[str]:
    source_files = collect_files(source)
    target_files = collect_files(target)
    findings: list[str] = []

    for relative in sorted(source_files.keys() - target_files.keys()):
        findings.append(f"missing: {relative}")
    for relative in sorted(target_files.keys() - source_files.keys()):
        findings.append(f"extra: {relative}")
    for relative in sorted(source_files.keys() & target_files.keys()):
        if digest(source_files[relative]) != digest(target_files[relative]):
            findings.append(f"different: {relative}")

    return findings


def apply_sync(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for relative, source_path in collect_files(source).items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        required=True,
        type=Path,
        help="Repository root whose site/ directory is the behavioral source of truth.",
    )
    parser.add_argument(
        "--target-root",
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help="Public repository root. Defaults to this repository.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Replace target site/ byte-for-byte before checking it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source_root.resolve() / "site"
    target = args.target_root.resolve() / "site"

    if not source.is_dir():
        print(f"error: source runtime does not exist: {source}", file=sys.stderr)
        return 2

    if args.apply:
        apply_sync(source, target)

    findings = compare(source, target)
    if findings:
        print("public runtime differs from the source of truth:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1

    print(f"public runtime matches source: {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
