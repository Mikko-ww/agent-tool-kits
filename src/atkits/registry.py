"""Catalog retrieval and cache management."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from pathlib import Path

from atkits.github import GitHubReleaseClient
from atkits.home import AtkitsHome
from atkits.models import AssetVersion, Catalog, RegistryError


class RegistryClient:
    """Read and cache the release catalog from GitHub."""

    def __init__(
        self, home: AtkitsHome, github: GitHubReleaseClient, *, release_tag: str = "registry"
    ) -> None:
        self.home = home
        self.github = github
        self.release_tag = release_tag

    def refresh(self) -> Catalog:
        release = self.github.get_release_by_tag(self.release_tag)
        asset_id = _catalog_asset_id(release)
        home = self.home
        home.tmp_path.mkdir(parents=True, exist_ok=True)
        temporary = home.tmp_path / f"catalog.json.tmp-{os.getpid()}-{uuid.uuid4().hex}"
        try:
            self.github.download_asset(asset_id, temporary)
            text = temporary.read_text(encoding="utf-8")
            catalog = Catalog(_parse_json(text))
            _atomic_write_text(home.catalog_path, text)
            return catalog
        finally:
            if temporary.exists():
                temporary.unlink()

    def cached(self) -> Catalog:
        if not self.home.catalog_path.is_file():
            raise RegistryError("catalog cache is missing")
        text = self.home.catalog_path.read_text(encoding="utf-8")
        return Catalog(_parse_json(text))

    def resolve(self, kind: str, name: str, version: str | None = None) -> AssetVersion:
        catalog = self.cached()
        if version is None:
            return catalog.latest(kind, name)
        return catalog.require_version(kind, name, version)


def _catalog_asset_id(release: Mapping[str, object]) -> int:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise RegistryError("GitHub release has no assets")
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == "catalog.json":
            asset_id = asset.get("id")
            if isinstance(asset_id, int) and not isinstance(asset_id, bool):
                return asset_id
    raise RegistryError("GitHub release does not contain catalog.json")


def _parse_json(text: str) -> dict[str, object]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RegistryError("catalog is not valid JSON") from exc
    if not isinstance(data, dict):
        raise RegistryError("catalog must be an object")
    return data


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
