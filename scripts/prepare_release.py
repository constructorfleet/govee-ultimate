"""Command line interface for preparing automated releases."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from .versioning import prepare_release


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the release preparation workflow."""

    parser = argparse.ArgumentParser(description="Prepare the next release version")
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to the Home Assistant manifest file to update",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        default=None,
        help="Optional path to a GitHub Actions output file",
    )
    args = parser.parse_args(argv)

    version = prepare_release(args.manifest)
    sys.stdout.write(f"{version}\n")

    if args.github_output is not None:
        args.github_output.parent.mkdir(parents=True, exist_ok=True)
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"version={version}\n")

    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via CLI
    raise SystemExit(main())
