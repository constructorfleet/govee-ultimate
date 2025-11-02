"""CLI to bump the project version at a given level.

This script updates the Home Assistant manifest version and prints the
new version to stdout. It is intended to be called from a GitHub Actions
workflow that runs on a PR branch.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from .versioning import bump_version


def main(argv: list[str] | None = None) -> int:
    """Bump the project version and commit the change.

    Returns exit code 0 on success.
    """
    parser = argparse.ArgumentParser(description="Bump project version")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--level",
        choices=("patch", "minor", "major"),
        required=True,
        help="Which semantic level to bump",
    )
    args = parser.parse_args(argv)

    new_version = bump_version(args.manifest, args.level)
    print(new_version)

    # Commit and push changes. Caller should ensure git is configured and
    # that credentials are available (for example via GITHUB_TOKEN).
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ],
        check=True,
    )
    subprocess.run(["git", "add", str(args.manifest)], check=True)
    subprocess.run(["git", "commit", "-m", f"chore(release): bump {args.level} to {new_version}"], check=True)
    subprocess.run(["git", "push", "--set-upstream", "origin", "HEAD"], check=True)

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
