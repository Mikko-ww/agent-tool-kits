"""Core domain models for the release-registry based atkits CLI."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from semver import Version

ASSET_KINDS = frozenset({"skill", "plugin", "cli"})
TARGET_SCOPES = frozenset({"global", "project", "editable"})
INSTALL_STRATEGIES = frozenset({"symlink", "copy", "editable"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RegistryError(ValueError):
    """Raised when catalog or install-target data is invalid."""


@dataclass(frozen=True)
class AssetVersion:
    """One immutable release artifact for a skill, plugin, or the CLI."""

    kind: str
    name: str
    version: str
    asset_id: int
    archive: str
    sha256: str
    source_revision: str | None = None
    description: str | None = None
    parsed_version: Version = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in ASSET_KINDS:
            raise RegistryError(f"unsupported asset kind {self.kind!r}")
        _validate_name(self.name)
        if not isinstance(self.version, str):
            raise RegistryError(f"{self.name}: version must be a string")
        try:
            object.__setattr__(self, "parsed_version", Version.parse(self.version))
        except ValueError as exc:
            raise RegistryError(f"invalid SemVer {self.version!r} for {self.name}") from exc
        if isinstance(self.asset_id, bool) or not isinstance(self.asset_id, int):
            raise RegistryError(f"{self.name}: asset_id must be an integer")
        if self.asset_id <= 0:
            raise RegistryError(f"{self.name}: asset_id must be positive")
        if not isinstance(self.archive, str) or not self.archive:
            raise RegistryError(f"{self.name}: archive must be a non-empty string")
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256):
            raise RegistryError(f"{self.name}: sha256 must be 64 lowercase hex characters")
        _validate_optional_str(self.name, "source_revision", self.source_revision)
        _validate_optional_str(self.name, "description", self.description)


@dataclass(frozen=True)
class InstallTarget:
    """A physical installation target and the logical platforms consuming it."""

    kind: str
    name: str
    scope: str
    project_id: str | None
    version: str | None
    target_id: str
    path: Path
    strategy: str
    consumers: tuple[str, ...]
    package_path: Path | None = None
    source_path: Path | None = None
    artifact_sha256: str | None = None
    content_sha256: str | None = None

    @property
    def target_path(self) -> Path:
        return self.path

    def key(self) -> str:
        if self.scope == "project":
            return f"{self.kind}:{self.name}:project:{self.project_id}:{self.target_id}"
        return f"{self.kind}:{self.name}:{self.scope}:{self.target_id}"


@dataclass(frozen=True)
class CatalogPreset:
    name: str
    scope: str
    platforms: tuple[str, ...]
    method: str


class Catalog:
    """Validated in-memory representation of catalog.json."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        if data.get("schema_version") != 1:
            raise RegistryError(
                f"unsupported catalog schema_version {data.get('schema_version')!r}"
            )
        self._assets: dict[str, dict[str, AssetVersion]] = {}
        self._external_skills = _parse_external_skills(data.get("external_skills"))
        self._presets = _parse_presets(data.get("collection"))
        for kind in ("skill", "plugin", "cli"):
            section_key = "skills" if kind == "skill" else "plugins" if kind == "plugin" else "cli"
            section = data.get(section_key) or {}
            if not isinstance(section, Mapping):
                raise RegistryError(f"catalog section {section_key!r} must be a mapping")
            if kind == "cli":
                versions = section.get("versions")
                if not versions:
                    self._assets[kind] = {}
                else:
                    self._assets[kind] = self._parse_section(kind, {"atkits": section})
            else:
                self._assets[kind] = self._parse_section(kind, section)

    def _parse_section(self, kind: str, section: Mapping[str, Any]) -> dict[str, AssetVersion]:
        parsed: dict[str, AssetVersion] = {}
        for name, raw_versions in section.items():
            _validate_name(str(name))
            if not isinstance(raw_versions, Mapping):
                raise RegistryError(f"{kind} {name}: version mapping must be an object")
            versions = raw_versions.get("versions")
            if not isinstance(versions, Mapping) or not versions:
                raise RegistryError(f"{kind} {name}: versions must be a non-empty mapping")
            assets: list[AssetVersion] = []
            for version, raw in versions.items():
                if not isinstance(raw, Mapping):
                    raise RegistryError(f"{kind} {name}@{version}: artifact must be an object")
                context = f"{kind} {name}@{version}"
                assets.append(
                    AssetVersion(
                        kind=kind,
                        name=str(name),
                        version=str(version),
                        asset_id=_required_int(context, raw, "asset_id"),
                        archive=_required_str(context, raw, "archive"),
                        sha256=_required_str(context, raw, "sha256"),
                        source_revision=_optional_str(context, raw, "source_revision"),
                        description=_optional_str(context, raw, "description"),
                    )
                )
            _reject_duplicate_precedence(name, assets)
            parsed[str(name)] = {asset.version: asset for asset in assets}
        return parsed

    def external_skills(self) -> dict[str, dict[str, object]]:
        return dict(self._external_skills)

    def presets(self) -> dict[str, CatalogPreset]:
        return dict(self._presets)

    def preset(self, name: str) -> CatalogPreset:
        try:
            return self._presets[name]
        except KeyError as exc:
            raise RegistryError(f"preset {name!r} not found") from exc

    def names(self, kind: str) -> list[str]:
        if kind not in ASSET_KINDS:
            raise RegistryError(f"unsupported asset kind {kind!r}")
        return sorted(self._assets[kind])

    def latest(self, kind: str, name: str) -> AssetVersion:
        versions = self._versions(kind, name)
        stable = [asset for asset in versions.values() if asset.parsed_version.prerelease is None]
        if not stable:
            raise RegistryError(f"{name}: no stable version available")
        return max(stable, key=lambda asset: asset.parsed_version)

    def require_version(self, kind: str, name: str, version: str) -> AssetVersion:
        try:
            return self._versions(kind, name)[version]
        except KeyError as exc:
            raise RegistryError(f"{name}@{version} not found") from exc

    def _versions(self, kind: str, name: str) -> dict[str, AssetVersion]:
        if kind not in ASSET_KINDS:
            raise RegistryError(f"unsupported asset kind {kind!r}")
        try:
            return self._assets[kind][name]
        except KeyError as exc:
            raise RegistryError(f"{kind} {name!r} not found") from exc


def _parse_external_skills(raw: object) -> dict[str, dict[str, object]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise RegistryError("external_skills must be a mapping")
    result: dict[str, dict[str, object]] = {}
    for name, entry in raw.items():
        _validate_name(str(name))
        if not isinstance(entry, Mapping):
            raise RegistryError(f"external skill {name}: entry must be an object")
        source = entry.get("source")
        if not isinstance(source, str) or not source:
            raise RegistryError(f"external skill {name}: source must be a non-empty string")
        result[str(name)] = dict(entry)
    return result


def _parse_presets(raw: object) -> dict[str, CatalogPreset]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise RegistryError("collection must be a mapping")
    presets_raw = raw.get("presets")
    if presets_raw is None:
        return {}
    if not isinstance(presets_raw, Mapping):
        raise RegistryError("collection.presets must be a mapping")
    result: dict[str, CatalogPreset] = {}
    for name, entry in presets_raw.items():
        _validate_name(str(name))
        if not isinstance(entry, Mapping):
            raise RegistryError(f"preset {name}: entry must be an object")
        scope = entry.get("scope")
        platforms = entry.get("platforms")
        method = entry.get("method", "symlink")
        if scope not in {"global", "project"}:
            raise RegistryError(f"preset {name}: invalid scope {scope!r}")
        if not isinstance(platforms, list) or not platforms:
            raise RegistryError(f"preset {name}: platforms must be a non-empty list")
        if not all(isinstance(platform, str) and platform for platform in platforms):
            raise RegistryError(f"preset {name}: platforms must be strings")
        if method not in {"symlink", "copy"}:
            raise RegistryError(f"preset {name}: invalid method {method!r}")
        result[str(name)] = CatalogPreset(
            name=str(name),
            scope=str(scope),
            platforms=tuple(platforms),
            method=str(method),
        )
    return result


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not name or not _NAME_RE.fullmatch(name):
        raise RegistryError(f"invalid asset name {name!r}")


def _required_int(context: str, raw: Mapping[str, Any], key: str) -> int:
    if key not in raw:
        raise RegistryError(f"{context}: {key} is required")
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise RegistryError(f"{context}: {key} must be an integer")
    return value


def _required_str(context: str, raw: Mapping[str, Any], key: str) -> str:
    if key not in raw:
        raise RegistryError(f"{context}: {key} is required")
    value = raw[key]
    if not isinstance(value, str) or not value:
        raise RegistryError(f"{context}: {key} must be a non-empty string")
    return value


def _optional_str(context: str, raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    _validate_optional_str(context, key, value)
    return value


def _validate_optional_str(context: str, key: str, value: Any) -> None:
    if value is not None and not isinstance(value, str):
        raise RegistryError(f"{context}: {key} must be a string or null")


def _reject_duplicate_precedence(name: str, assets: list[AssetVersion]) -> None:
    for index, asset in enumerate(assets):
        for other in assets[index + 1 :]:
            if asset.parsed_version == other.parsed_version:
                raise RegistryError(
                    f"{name}: duplicate version entries with same precedence: "
                    f"{asset.version}, {other.version}"
                )
