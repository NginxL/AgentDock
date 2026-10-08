#!/usr/bin/env python3
"""Create a distributable app; never installs it or opens the user's database."""

import argparse
import os
import sys
from pathlib import Path

from macos_bundle import build_sources, bundle_at


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument(
        "--python-runtime",
        type=Path,
        required=True,
        help="Root of a portable Python 3.11+ distribution",
    )
    parser.add_argument("--identity", default="-", help="Developer ID or - for ad-hoc")
    parser.add_argument(
        "--build-number", default=os.environ.get("GITHUB_RUN_NUMBER", "36")
    )
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("macOS is required")
    if (args.output / "AgentDock.app").exists():
        parser.error(
            "Output already contains AgentDock.app; choose a new output directory"
        )
    binaries = build_sources()
    print(
        bundle_at(
            args.output, binaries, args.python_runtime, args.identity, args.build_number
        )
    )


if __name__ == "__main__":
    main()
