#!/usr/bin/env python3
"""Bump the version in pyproject.toml. Usage: python scripts/bump_version.py [patch|minor|major]"""

import re
import sys
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
VERSION_RE = re.compile(r'(version\s*=\s*")(\d+)\.(\d+)\.(\d+)(")')


def bump(part: str) -> None:
    text = PYPROJECT.read_text()
    m = VERSION_RE.search(text)
    if not m:
        print("ERROR: Could not find version in pyproject.toml", file=sys.stderr)
        sys.exit(1)

    major, minor, patch = int(m.group(2)), int(m.group(3)), int(m.group(4))
    old = f"{major}.{minor}.{patch}"

    if part == "patch":
        patch += 1
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        print(f"ERROR: Unknown bump part '{part}'. Use patch, minor, or major.", file=sys.stderr)
        sys.exit(1)

    new = f"{major}.{minor}.{patch}"
    text = VERSION_RE.sub(rf"\g<1>{new}\5", text, count=1)
    PYPROJECT.write_text(text)
    print(f"{old} -> {new}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/bump_version.py [patch|minor|major]", file=sys.stderr)
        sys.exit(1)
    bump(sys.argv[1])
