"""Filesystem installation strategies for physical targets."""

from __future__ import annotations

import dataclasses
import os
import shutil
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from atkits.home import AtkitsHome
from atkits.models import InstallTarget
from atkits.packages import sha256_tree


class InstallConflict(RuntimeError):
    """Raised when a target cannot be safely replaced or removed."""


class BackupStore:
    """Move replaced real directories into a timestamped backup area."""

    def __init__(self, home: AtkitsHome) -> None:
        self.root = home.backup_path

    def backup(self, path: Path) -> Path:
        if path.is_symlink():
            raise InstallConflict(f"refusing to back up symlink: {path}")
        if not path.exists():
            raise InstallConflict(f"cannot back up missing path: {path}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination_dir = self.root / f"backup-{stamp}-{uuid.uuid4().hex[:8]}"
        destination_dir.mkdir(parents=True, exist_ok=False)
        destination = destination_dir / path.name
        shutil.move(str(path), str(destination))
        return destination


class Installer:
    """Install and uninstall symlink, copy, and editable targets safely."""

    def __init__(self, home: AtkitsHome, backup_store: BackupStore | None = None) -> None:
        self.home = home
        self.backup_store = backup_store or BackupStore(home)

    def install(self, record: InstallTarget, package_dir: Path | None) -> InstallTarget:
        if record.strategy == "editable":
            source = record.source_path
            if source is None:
                raise InstallConflict("editable target requires source_path")
            self._install_symlink(record, source)
            return record
        if record.strategy == "symlink":
            if package_dir is None:
                raise InstallConflict("symlink target requires package_dir")
            self._install_symlink(record, package_dir)
            return record
        if record.strategy == "copy":
            if package_dir is None:
                raise InstallConflict("copy target requires package_dir")
            return self._install_copy(record, package_dir)
        raise InstallConflict(f"unsupported strategy {record.strategy!r}")

    def uninstall(self, record: InstallTarget, consumers: Iterable[str]) -> InstallTarget:
        remaining = set(record.consumers) - set(consumers)
        updated = dataclasses.replace(record, consumers=tuple(sorted(remaining)))
        if remaining:
            return updated

        target = record.target_path
        if not target.exists() and not target.is_symlink():
            return updated

        if record.strategy in {"symlink", "editable"}:
            expected = record.source_path if record.strategy == "editable" else record.package_path
            if expected is None:
                raise InstallConflict("managed symlink target has no expected source")
            if not target.is_symlink() or target.resolve() != expected.resolve():
                raise InstallConflict(f"target is not managed by atkits: {target}")
            target.unlink()
            return updated

        if record.strategy == "copy":
            if not target.is_dir():
                raise InstallConflict(f"copy target is not a directory: {target}")
            if sha256_tree(target) != record.content_sha256:
                raise InstallConflict(f"local modification detected: {target}")
            self.backup_store.backup(target)
            return updated

        raise InstallConflict(f"unsupported strategy {record.strategy!r}")

    def health(self, record: InstallTarget) -> bool:
        target = record.target_path
        if record.strategy in {"symlink", "editable"}:
            expected = record.source_path if record.strategy == "editable" else record.package_path
            if expected is None or not target.is_symlink():
                return False
            return target.resolve() == expected.resolve()
        if record.strategy == "copy":
            if not target.is_dir():
                return False
            return sha256_tree(target) == record.content_sha256
        return False

    def _install_symlink(self, record: InstallTarget, source: Path) -> None:
        target = record.target_path
        expected = source.resolve()
        if target.exists() or target.is_symlink():
            if target.is_symlink() and target.resolve() == expected:
                target.unlink()
            else:
                raise InstallConflict(f"target is not managed by atkits: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(str(expected), str(target), target_is_directory=True)

    def _install_copy(self, record: InstallTarget, package_dir: Path) -> InstallTarget:
        target = record.target_path
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_dir():
                raise InstallConflict(f"target is not a managed copy: {target}")
            if sha256_tree(target) != record.content_sha256:
                raise InstallConflict(f"local modification detected: {target}")
            self.backup_store.backup(target)

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(package_dir, target)
        content_sha256 = sha256_tree(target)
        return dataclasses.replace(record, content_sha256=content_sha256)
