"""Build catalog.json from GitHub releases and collection inputs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from semver import Version

_TAG_RE = re.compile(r"^(skill|plugin)-(.+)-v([^+]+(?:\+[^+]+)?)$")
_CLI_TAG_RE = re.compile(r"^cli-v([^+]+(?:\+[^+]+)?)$")


class CatalogBuildError(ValueError):
    pass


def build_catalog(
    releases: list[dict[str, Any]],
    favorites: dict[str, Any],
    collection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog: dict[str, Any] = {
        "schema_version": 1,
        "skills": {},
        "plugins": {},
        "cli": {"latest": None, "versions": {}},
        "external_skills": {},
        "collection": {"presets": {}},
    }
    for release in releases:
        tag = release.get("tag_name")
        if not isinstance(tag, str):
            continue
        if tag == "registry":
            continue
        cli_match = _CLI_TAG_RE.fullmatch(tag)
        if cli_match:
            _add_cli_version(catalog, cli_match.group(1), release)
            continue
        match = _TAG_RE.fullmatch(tag)
        if not match:
            continue
        kind, name, version = match.groups()
        _add_asset_version(catalog, kind, name, version, release)

    for section in ("skills", "plugins"):
        for name, versions in catalog[section].items():
            versions["latest"] = _latest_stable(versions["versions"])
    if catalog["cli"]["versions"]:
        catalog["cli"]["latest"] = _latest_stable(catalog["cli"]["versions"])

    external = favorites.get("external_skills")
    if isinstance(external, dict):
        catalog["external_skills"] = external
    presets = favorites.get("presets")
    if collection is not None:
        collection_presets = collection.get("presets")
        if isinstance(collection_presets, dict):
            presets = collection_presets
    if isinstance(presets, dict):
        catalog["collection"]["presets"] = presets
    return catalog


def _add_asset_version(
    catalog: dict[str, Any], kind: str, name: str, version: str, release: dict[str, Any]
) -> None:
    try:
        Version.parse(version)
    except ValueError as exc:
        raise CatalogBuildError(f"invalid SemVer in tag {release.get('tag_name')!r}") from exc
    assets = release.get("assets")
    asset = _select_asset(assets, ".tar.gz", f"release {name}@{version}")
    section = catalog["skills"] if kind == "skill" else catalog["plugins"]
    entry = section.setdefault(name, {"latest": None, "versions": {}})
    if version in entry["versions"]:
        raise CatalogBuildError(f"duplicate version {name}@{version}")
    entry["versions"][version] = {
        "asset_id": asset.get("id"),
        "archive": asset.get("name"),
        "sha256": _sha256_from_asset(asset),
        "source_revision": release.get("target_commitish"),
    }


def _add_cli_version(catalog: dict[str, Any], version: str, release: dict[str, Any]) -> None:
    try:
        Version.parse(version)
    except ValueError as exc:
        raise CatalogBuildError(f"invalid CLI SemVer {version!r}") from exc
    assets = release.get("assets")
    asset = _select_asset(assets, ".whl", f"CLI {version}")
    if version in catalog["cli"]["versions"]:
        raise CatalogBuildError(f"duplicate CLI version {version}")
    catalog["cli"]["versions"][version] = {
        "asset_id": asset.get("id"),
        "archive": asset.get("name"),
        "sha256": _sha256_from_asset(asset),
        "source_revision": release.get("target_commitish"),
    }


def _select_asset(assets: Any, suffix: str, context: str) -> dict[str, Any]:
    if not isinstance(assets, list):
        raise CatalogBuildError(f"{context} has no asset list")
    candidates = [
        asset
        for asset in assets
        if isinstance(asset, dict) and str(asset.get("name", "")).endswith(suffix)
    ]
    if len(candidates) != 1:
        raise CatalogBuildError(f"{context} must contain exactly one {suffix} asset")
    return candidates[0]


def _sha256_from_asset(asset: dict[str, Any]) -> Any:
    value = asset.get("sha256")
    if value is not None:
        return value
    digest = asset.get("digest")
    if isinstance(digest, str) and digest.startswith("sha256:"):
        return digest.removeprefix("sha256:")
    return digest


def _latest_stable(versions: dict[str, Any]) -> str | None:
    stable = []
    for version in versions:
        parsed = Version.parse(version)
        if parsed.prerelease is None:
            stable.append(parsed)
    return str(max(stable)) if stable else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build atkits catalog.json")
    parser.add_argument("releases_json", type=Path)
    parser.add_argument("favorites_yaml", type=Path)
    parser.add_argument("collection_yaml", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    from ruamel.yaml import YAML

    releases = json.loads(args.releases_json.read_text(encoding="utf-8"))
    favorites = YAML(typ="safe", pure=True).load(args.favorites_yaml.read_text(encoding="utf-8"))
    collection = YAML(typ="safe", pure=True).load(args.collection_yaml.read_text(encoding="utf-8"))
    catalog = build_catalog(releases, favorites, collection)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
