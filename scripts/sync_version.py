#!/usr/bin/env python3
"""Sync version metadata from the repo-root VERSION file."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "VERSION"
TARGETS = [
    REPO_ROOT / "paper_plane_x_backend" / "pyproject.toml",
    REPO_ROOT / "paper_plane_x_cli" / "pyproject.toml",
]
UV_LOCK_TARGETS = [
    (
        REPO_ROOT / "paper_plane_x_backend" / "uv.lock",
        "paper-plane-x-backend",
    ),
    (
        REPO_ROOT / "paper_plane_x_cli" / "uv.lock",
        "paper-plane-x-cli",
    ),
]
FRONTEND_PACKAGE_JSON = REPO_ROOT / "paper_plane_x_frontend" / "package.json"
ZOTERO_PACKAGE_JSON = REPO_ROOT / "paper_plane_x_zotero" / "package.json"
ZOTERO_PACKAGE_LOCK = REPO_ROOT / "paper_plane_x_zotero" / "package-lock.json"


def read_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Invalid version in {VERSION_FILE}: {version!r}")
    return version


def write_version(version: str) -> None:
    VERSION_FILE.write_text(f"{version}\n", encoding="utf-8")


def sync_toml_version(path: Path, version: str) -> None:
    original = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        original,
        count=1,
    )
    if count != 1:
        raise ValueError(f"Could not update version field in {path}")
    path.write_text(updated, encoding="utf-8")


def sync_uv_lock_project_version(
    path: Path,
    project_name: str,
    version: str,
) -> None:
    original = path.read_text(encoding="utf-8")
    package_match = next(
        (
            match
            for match in re.finditer(
                r"(?ms)^\[\[package\]\]\n.*?(?=^\[\[package\]\]\n|\Z)",
                original,
            )
            if re.search(
                rf'(?m)^name = "{re.escape(project_name)}"$',
                match.group(),
            )
        ),
        None,
    )
    if package_match is None:
        raise ValueError(f"Could not find project {project_name!r} in {path}")

    package_start = package_match.start()
    package_end = package_match.end()
    package_block = package_match.group()
    updated_block, count = re.subn(
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        package_block,
        count=1,
    )
    if count != 1:
        raise ValueError(
            f"Could not update project version for {project_name!r} in {path}"
        )
    path.write_text(
        original[:package_start] + updated_block + original[package_end:],
        encoding="utf-8",
    )


def sync_package_json_version(path: Path, version: str) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = version
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sync_package_lock_version(path: Path, version: str) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = version
    root_package = payload.get("packages", {}).get("")
    if isinstance(root_package, dict):
        root_package["version"] = version
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--set",
        dest="target_version",
        help="Write a new x.y.z version to VERSION before syncing consumers.",
    )
    args = parser.parse_args()

    if args.target_version:
        if not re.fullmatch(r"\d+\.\d+\.\d+", args.target_version):
            raise ValueError("--set must be in x.y.z format")
        write_version(args.target_version)

    version = read_version()

    for path in TARGETS:
        sync_toml_version(path, version)
    for path, project_name in UV_LOCK_TARGETS:
        sync_uv_lock_project_version(path, project_name, version)
    sync_package_json_version(FRONTEND_PACKAGE_JSON, version)
    sync_package_json_version(ZOTERO_PACKAGE_JSON, version)
    sync_package_lock_version(ZOTERO_PACKAGE_LOCK, version)

    print(f"Synced version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
