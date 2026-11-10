"""Build one immutable skill or plugin release archive."""

from __future__ import annotations

import argparse
import hashlib
import tarfile
from pathlib import Path

from ruamel.yaml import YAML

IGNORED_NAMES = {".DS_Store", "__pycache__", ".git"}


class PackageAssetError(ValueError):
    """Raised when an asset cannot be packaged safely."""


def package_asset(kind: str, name: str, version: str, repo_root: Path, output_dir: Path) -> Path:
    if kind not in {"skill", "plugin"}:
        raise PackageAssetError(f"unsupported asset kind {kind!r}")
    source_dir = _asset_dir(kind, name, repo_root)
    metadata = _load_metadata(kind, source_dir)
    if metadata.get("name") != name:
        raise PackageAssetError(f"asset name mismatch: expected {name!r}")
    actual_version = _version_from_metadata(metadata)
    if actual_version != version:
        raise PackageAssetError(
            f"asset version mismatch for {name}: expected {version!r}, got {actual_version!r}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"{name}-{version}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in sorted(source_dir.rglob("*")):
            if any(part in IGNORED_NAMES for part in path.parts):
                continue
            if path.is_symlink():
                raise PackageAssetError(f"refusing to package symlink: {path}")
            if not path.is_file():
                continue
            archive.add(path, arcname=f"{name}/{path.relative_to(source_dir)}", recursive=False)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (output_dir / f"{archive_path.name}.sha256").write_text(
        f"{digest}  {archive_path.name}\n", encoding="utf-8"
    )
    return archive_path


def _asset_dir(kind: str, name: str, repo_root: Path) -> Path:
    directory = "skills" if kind == "skill" else "plugins"
    source_dir = repo_root / directory / name
    if not source_dir.is_dir():
        raise PackageAssetError(f"missing asset directory: {source_dir}")
    return source_dir


def _load_metadata(kind: str, source_dir: Path) -> dict[str, object]:
    yaml = YAML(typ="safe", pure=True)
    if kind == "skill":
        skill_file = source_dir / "SKILL.md"
        if not skill_file.is_file():
            raise PackageAssetError(f"missing SKILL.md: {skill_file}")
        text = skill_file.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise PackageAssetError("SKILL.md must start with frontmatter")
        end = text.find("\n---\n", 4)
        if end < 0:
            raise PackageAssetError("SKILL.md frontmatter is not closed")
        data = yaml.load(text[4:end])
    else:
        manifest = source_dir / "plugin.yaml"
        if not manifest.is_file():
            raise PackageAssetError(f"missing plugin.yaml: {manifest}")
        data = yaml.load(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PackageAssetError("asset metadata must be a mapping")
    return data


def _version_from_metadata(metadata: dict[str, object]) -> object:
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return nested.get("version")
    return metadata.get("version")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build one atkits release asset")
    parser.add_argument("kind", choices=["skill", "plugin"])
    parser.add_argument("name")
    parser.add_argument("version")
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    archive = package_asset(args.kind, args.name, args.version, args.repo_root, args.output_dir)
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
