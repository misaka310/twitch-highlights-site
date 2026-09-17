from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


def build_manifest() -> dict[str, str]:
    if not PUBLIC.is_dir():
        raise SystemExit("public reproducibility check failed: public/ does not exist")
    manifest: dict[str, str] = {}
    for path in sorted(candidate for candidate in PUBLIC.rglob("*") if candidate.is_file()):
        relative = path.relative_to(PUBLIC).as_posix()
        manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def build_public() -> None:
    """Use the repository shell explicitly on Windows as well as Unix."""

    if os.name != "nt":
        command = ["sh", "scripts/build_public.sh"]
    else:
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        bash = str(git_bash) if git_bash.is_file() else (shutil.which("bash") or "bash")
        command = [bash, "-lc", "sh scripts/build_public.sh"]
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    first = build_manifest()
    build_public()
    second = build_manifest()
    if first != second:
        first_keys = set(first)
        second_keys = set(second)
        added = sorted(second_keys - first_keys)
        removed = sorted(first_keys - second_keys)
        changed = sorted(key for key in first_keys & second_keys if first[key] != second[key])
        raise SystemExit(
            "public reproducibility check failed: "
            f"added={added} removed={removed} changed={changed}"
        )
    print(f"public reproducibility check passed ({len(first)} files)")


if __name__ == "__main__":
    main()
