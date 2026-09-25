#!/usr/bin/env python3
"""Validate OpenAPI YAML files under service api/ directories."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

SPEC_GLOBS = (
    REPO_ROOT / "chinta-auth" / "api" / "auth-openapi.yml",
    REPO_ROOT / "chinta-gateway" / "api" / "gateway-openapi.yml",
    REPO_ROOT / "chinta" / "api" / "chinta-openapi.yml",
)


def validate_spec(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"missing file: {path}")
        return errors

    with path.open() as f:
        try:
            doc = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            errors.append(f"{path}: YAML parse error: {exc}")
            return errors

    if not isinstance(doc, dict):
        errors.append(f"{path}: root must be a mapping")
        return errors

    if doc.get("openapi", "").split(".")[0] != "3":
        errors.append(f"{path}: expected openapi 3.x, got {doc.get('openapi')!r}")

    info = doc.get("info")
    if not isinstance(info, dict) or not info.get("title") or not info.get("version"):
        errors.append(f"{path}: info.title and info.version are required")

    paths = doc.get("paths")
    if not isinstance(paths, dict) or not paths:
        errors.append(f"{path}: paths must be a non-empty mapping")

    return errors


def main() -> int:
    all_errors: list[str] = []
    for spec_path in SPEC_GLOBS:
        all_errors.extend(validate_spec(spec_path))

    if all_errors:
        print("OpenAPI validation failed:", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"OK: validated {len(SPEC_GLOBS)} OpenAPI spec(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
