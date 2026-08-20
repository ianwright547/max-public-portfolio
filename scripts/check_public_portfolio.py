"""Fail-closed audit for the recruiter-facing, dummy-data repository copy."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


TOKEN_PATTERNS = (
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
)
FORBIDDEN_PATH_NAMES = {
    ".env",
    ".env.local",
    "max.db",
    "vercel_client_import.private.json",
    "Max Product Definition Main 3b0eba2b3f338077acf6f656a1404efb.md",
}


def audit(root: Path) -> list[str]:
    failures: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name in FORBIDDEN_PATH_NAMES or path.suffix == ".db":
            failures.append(f"forbidden file: {path.relative_to(root)}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in TOKEN_PATTERNS:
            if pattern.search(text):
                failures.append(f"token-like text in: {path.relative_to(root)}")
                break

    notice = root / "PUBLIC_DATA_NOTICE.md"
    if not notice.exists() or "dummy data" not in notice.read_text(encoding="utf-8").casefold():
        failures.append("PUBLIC_DATA_NOTICE.md must explicitly identify dummy data")
    manifest = root / "data" / "vercel_client_import.json"
    if manifest.exists():
        content = manifest.read_text(encoding="utf-8").casefold()
        if "demo-auto.example.com" not in content:
            failures.append("integration manifest is not the sanitized demo manifest")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    failures = audit(args.root.resolve())
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("Public portfolio audit passed: dummy-data and secret/path boundaries are clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
