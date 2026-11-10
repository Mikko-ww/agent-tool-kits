"""Dispatch one release tag to package_asset.py."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_TAG_RE = re.compile(r"^(skill|plugin)-(.+)-v(.+)$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build asset for one release tag")
    parser.add_argument("tag")
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    match = _TAG_RE.fullmatch(args.tag)
    if not match:
        print(f"unsupported release tag: {args.tag}", file=sys.stderr)
        return 2
    kind, name, version = match.groups()
    command = [
        sys.executable,
        str(Path(__file__).with_name("package_asset.py")),
        kind,
        name,
        version,
        str(args.repo_root),
        str(args.output_dir),
    ]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
