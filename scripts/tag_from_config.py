#!/usr/bin/env python3
"""Single source of truth: version in config.yaml. Git tag v{version} is derived from it."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"


def read_version_from_config() -> str:
    text = CONFIG.read_text(encoding="utf-8")
    m = re.search(r"^version:\s*(.+)$", text, re.MULTILINE)
    if not m:
        print("Could not find version: in config.yaml", file=sys.stderr)
        sys.exit(1)
    raw = m.group(1).split("#", 1)[0].strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1]
    raw = raw.strip()
    if not raw or raw.startswith("{"):
        print("Unexpected version value in config.yaml", file=sys.stderr)
        sys.exit(1)
    return raw


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-matches-tag",
        action="store_true",
        help="Exit 0 only if config.yaml version matches GITHUB_REF_NAME (e.g. v1.0.2). For CI.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the tag that would be created, do not run git tag.",
    )
    parser.add_argument(
        "--print-tag",
        action="store_true",
        help="Print only the tag name (e.g. v1.0.2) to stdout. For shell scripts.",
    )
    args = parser.parse_args()
    version = read_version_from_config()
    tag = f"v{version}"

    if args.print_tag:
        print(tag)
        return

    if args.verify_matches_tag:
        ref = os.environ.get("GITHUB_REF_NAME", "")
        if not ref.startswith("v"):
            print("GITHUB_REF_NAME must be a tag like v1.0.2", file=sys.stderr)
            sys.exit(1)
        tagged = ref[1:]
        if tagged != version:
            print(
                f"Mismatch: config.yaml has version {version!r}, tag is {tagged!r}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"OK: config.yaml and tag {ref} both refer to {version}")
        return

    if args.dry_run:
        print(f"Would create annotated git tag: {tag} (from config.yaml version {version})")
        print(f"Then: git push origin {tag}")
        return

    cp = git("rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False)
    if cp.returncode == 0:
        print(f"Tag {tag} already exists. Bump version in config.yaml first.", file=sys.stderr)
        sys.exit(1)

    subprocess.run(
        ["git", "tag", "-a", tag, "-m", f"Release {version}"],
        cwd=ROOT,
        check=True,
    )
    print(f"Created {tag}. Push with: git push origin {tag}")


if __name__ == "__main__":
    main()
