"""Safe package extraction and content-addressed cache management."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tarfile
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath

from ruamel.yaml import YAML

from atkits.home import AtkitsHome
from atkits.models import AssetVersion

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
_PACKAGE_MARKER = ".atkits-package.json"


class PackageError(ValueError):
    """Raised when a release package is invalid or unsafe."""


class PackageStore:
    """Download, verify, extract, and cache versioned asset packages."""

    def __init__(self, home: AtkitsHome) -> None:
        self.home = home

    def path_for(self, kind: str, name: str, version: str) -> Path:
        kind_dir = "skills" if kind == "skill" else "plugins" if kind == "plugin" else kind
        return self.home.packages_path / kind_dir / name / version

    def ensure(self, asset: AssetVersion, downloader: Callable[[AssetVersion], Path]) -> Path:
        destination = self.path_for(asset.kind, asset.name, asset.version)
        if destination.exists():
            if self._cache_is_valid(destination, asset):
                return destination
            raise PackageError(f"package path already exists: {destination}")

        archive = downloader(asset)
        actual_hash = sha256_file(archive)
        if actual_hash != asset.sha256:
            raise PackageError(
                f"sha256 mismatch for {asset.kind} {asset.name}@{asset.version}: "
                f"expected {asset.sha256}, got {actual_hash}"
            )
        return self.extract(archive, asset.kind, asset.name, asset.version, asset=asset)

    def extract(
        self,
        archive: Path,
        kind: str,
        name: str,
        version: str,
        *,
        asset: AssetVersion | None = None,
    ) -> Path:
        destination = self.path_for(kind, name, version)
        if destination.exists():
            if asset is not None and self._cache_is_valid(destination, asset):
                return destination
            raise PackageError(f"package path already exists: {destination}")

        self.home.tmp_path.mkdir(parents=True, exist_ok=True)
        temporary = self.home.tmp_path / f"package-{os.getpid()}-{uuid.uuid4().hex}"
        temporary.mkdir()
        try:
            _safe_extract_tar(archive, temporary)
            package_root = temporary / name
            _validate_extracted_package(temporary, kind, name, version)
            if asset is not None:
                _write_package_marker(package_root, asset)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(package_root, destination)
            return destination
        finally:
            if temporary.exists():
                _remove_tree(temporary)

    def _cache_is_valid(self, destination: Path, asset: AssetVersion) -> bool:
        marker_path = destination / _PACKAGE_MARKER
        if not marker_path.is_file():
            return False
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        return (
            isinstance(marker, dict)
            and marker.get("kind") == asset.kind
            and marker.get("name") == asset.name
            and marker.get("version") == asset.version
            and marker.get("artifact_sha256") == asset.sha256
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise PackageError(f"cannot hash non-file path: {path}")
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise PackageError(f"cannot hash symlink: {item}")
        if not item.is_file():
            continue
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(item).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                _validate_tar_member(member)
            try:
                tar.extractall(destination, filter="data")
            except TypeError:
                tar.extractall(destination)
    except tarfile.TarError as exc:
        raise PackageError(f"invalid tar archive: {archive}") from exc


def _validate_tar_member(member: tarfile.TarInfo) -> None:
    name = member.name
    if not name or name.startswith("/") or "\\" in name:
        raise PackageError(f"unsafe path in archive: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise PackageError(f"unsafe path in archive: {name!r}")
    if member.issym() or member.islnk() or member.isdev():
        raise PackageError(f"unsafe entry in archive: {name!r}")
    if not (member.isfile() or member.isdir()):
        raise PackageError(f"unsafe entry in archive: {name!r}")


def _validate_extracted_package(root: Path, kind: str, name: str, version: str) -> None:
    package_root = root / name
    if not package_root.is_dir():
        raise PackageError(f"archive must contain package directory {name!r}")
    if kind == "skill":
        skill_file = package_root / "SKILL.md"
        if not skill_file.is_file():
            raise PackageError("skill package must contain SKILL.md")
        metadata = _parse_skill_frontmatter(skill_file)
    elif kind == "plugin":
        manifest = package_root / "plugin.yaml"
        if not manifest.is_file():
            raise PackageError("plugin package must contain plugin.yaml")
        metadata = _parse_yaml_file(manifest)
    else:
        return
    if metadata.get("name") != name:
        raise PackageError(f"package name mismatch: expected {name!r}")
    package_version = _package_version(metadata)
    if package_version != version:
        raise PackageError(f"package version mismatch: expected {version!r}")


def _parse_skill_frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise PackageError("SKILL.md must start with YAML frontmatter")
    return _parse_yaml_text(match.group(1))


def _parse_yaml_file(path: Path) -> dict[str, object]:
    return _parse_yaml_text(path.read_text(encoding="utf-8"))


def _parse_yaml_text(text: str) -> dict[str, object]:
    yaml = YAML(typ="safe", pure=True)
    try:
        data = yaml.load(text)
    except Exception as exc:
        raise PackageError("invalid YAML metadata") from exc
    if not isinstance(data, dict):
        raise PackageError("package metadata must be a mapping")
    return data


def _package_version(metadata: Mapping[str, object]) -> object:
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return nested.get("version")
    return metadata.get("version")


def _write_package_marker(root: Path, asset: AssetVersion) -> None:
    marker = {
        "kind": asset.kind,
        "name": asset.name,
        "version": asset.version,
        "artifact_sha256": asset.sha256,
    }
    (root / _PACKAGE_MARKER).write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _remove_tree(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()
    elif path.is_dir():
        for child in path.iterdir():
            _remove_tree(child)
        path.rmdir()
