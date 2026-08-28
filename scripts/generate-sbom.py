#!/usr/bin/env python3
"""Generate a compact CycloneDX JSON inventory from the three lock domains."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import tomllib
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("stem-studio.cdx.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    components = python_components()
    components += npm_components(root / "app/package-lock.json")
    components += cargo_components(root / "app/src-tauri/Cargo.lock")
    unique = {(item["purl"], item["version"]): item for item in components}
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "Stem Studio", "version": "0.1.0"}},
        "components": sorted(unique.values(), key=lambda item: item["purl"]),
    }
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(unique)} components to {args.output}")


def python_components() -> list[dict[str, str]]:
    result = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            normalized = name.lower().replace("_", "-")
            result.append(component(name, distribution.version, f"pkg:pypi/{normalized}@{distribution.version}"))
    return result


def npm_components(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = []
    for package_path, package in payload.get("packages", {}).items():
        if not package_path or not package.get("version"):
            continue
        name = package.get("name") or package_path.rsplit("node_modules/", 1)[-1]
        result.append(component(name, package["version"], f"pkg:npm/{name.replace('@', '%40')}@{package['version']}"))
    return result


def cargo_components(path: Path) -> list[dict[str, str]]:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    return [
        component(package["name"], package["version"], f"pkg:cargo/{package['name']}@{package['version']}")
        for package in payload.get("package", [])
    ]


def component(name: str, version: str, purl: str) -> dict[str, str]:
    return {"type": "library", "name": name, "version": version, "purl": purl}


if __name__ == "__main__":
    main()
