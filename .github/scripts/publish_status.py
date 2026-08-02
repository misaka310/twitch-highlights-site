from __future__ import annotations

import json
import os
import sys
import urllib.request


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: publish_status.py <state> <description>")
    state, description = sys.argv[1:]
    token = os.environ["GH_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]
    shas = {os.environ["HEAD_SHA"], os.environ["CHECK_SHA"]}
    payload = json.dumps(
        {
            "state": state,
            "context": "public-readiness",
            "description": description,
        }
    ).encode("utf-8")
    for sha in sorted(shas):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/statuses/{sha}",
            data=payload,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 201:
                raise SystemExit(f"status publication failed for {sha}: HTTP {response.status}")


if __name__ == "__main__":
    main()
