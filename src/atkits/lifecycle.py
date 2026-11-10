"""Coordinate registry, packages, platform targets, installation, and state."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from atkits.home import AtkitsHome
from atkits.installers import Installer
from atkits.models import AssetVersion, InstallTarget, RegistryError
from atkits.platforms import project_id, resolve_targets
from atkits.state import StateStore


class LifecycleError(RuntimeError):
    """Raised when a lifecycle operation cannot be completed."""


class InstallConflict(RuntimeError):
    """Raised when a target conflict prevents installation or uninstall."""


class RegistryProtocol(Protocol):
    def resolve(self, kind: str, name: str, version: str | None = None) -> AssetVersion: ...


class PackageStoreProtocol(Protocol):
    def ensure(self, asset: AssetVersion) -> Path: ...

    def cached_asset(self, kind: str, name: str, version: str) -> AssetVersion | None: ...


@dataclass(frozen=True)
class InstallResult:
    targets: tuple[InstallTarget, ...]

    @property
    def version(self) -> str | None:
        return self.targets[0].version

    @property
    def path(self) -> Path:
        return self.targets[0].path

    @property
    def project_id(self) -> str | None:
        return self.targets[0].project_id


@dataclass(frozen=True)
class UpdatePlan:
    affected_consumers: set[str]
    path: Path | None
    current_version: str | None
    latest_version: str


@dataclass(frozen=True)
class StatusReport:
    record: InstallTarget
    healthy: bool


class Lifecycle:
    """Install, update, uninstall, and inspect versioned assets."""

    def __init__(
        self,
        home: AtkitsHome,
        registry: RegistryProtocol,
        package_store: PackageStoreProtocol,
        installer: Installer,
        state: StateStore,
        *,
        os_name: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.home = home
        self.registry = registry
        self.package_store = package_store
        self.installer = installer
        self.state = state
        self.os_name = os_name or _current_os_name()
        self.env = dict(env or {})

    def install(
        self,
        kind: str,
        name: str,
        version: str | None = None,
        *,
        scope: str,
        platform_ids: list[str],
        method: str,
        project_root: Path | None = None,
    ) -> InstallResult:
        try:
            asset = self.registry.resolve(kind, name, version)
        except RegistryError:
            if version is None:
                raise
            asset = self.package_store.cached_asset(kind, name, version)
            if asset is None:
                raise
        if scope == "project":
            if project_root is None:
                raise LifecycleError("project scope requires project_root")
            cwd = project_root
            resolved_project_id = project_id(project_root)
        elif scope == "global":
            cwd = Path.cwd()
            resolved_project_id = None
        else:
            raise LifecycleError(f"unsupported scope {scope!r}")

        targets = resolve_targets(scope, platform_ids, cwd, self.os_name, self.env)
        if not targets:
            raise LifecycleError(f"no physical targets for platforms {platform_ids!r}")

        package_dir = self.package_store.ensure(asset)
        records: list[InstallTarget] = []
        for target in targets:
            record = InstallTarget(
                kind=kind,
                name=name,
                scope=scope,
                project_id=resolved_project_id,
                version=asset.version,
                target_id=target.target_id,
                path=target.path / name,
                strategy=method,
                consumers=target.consumers,
                package_path=package_dir,
                artifact_sha256=asset.sha256,
            )
            existing = self.state.get_target(
                kind, name, scope, resolved_project_id, target.target_id
            )
            if existing is not None and existing.version != record.version:
                existing_consumers = set(existing.consumers)
                requested_consumers = set(target.consumers)
                if target.shared or existing.path == record.path:
                    if not existing_consumers.issubset(requested_consumers):
                        raise InstallConflict(
                            f"shared target version mismatch for {name}: "
                            f"{existing.version} -> {record.version}"
                        )
            if existing is not None and existing.version != record.version:
                self.installer.uninstall(existing, existing.consumers)
            installed_record = self.installer.install(record, package_dir)
            self.state.put(installed_record)
            records.append(installed_record)
        return InstallResult(tuple(records))

    def install_editable(
        self,
        source_path: Path,
        *,
        scope: str,
        platform_ids: list[str],
        project_root: Path | None = None,
        name: str | None = None,
        kind: str = "skill",
    ) -> InstallResult:
        if scope == "project":
            if project_root is None:
                raise LifecycleError("project scope requires project_root")
            cwd = project_root
            resolved_project_id = project_id(project_root)
        elif scope == "global":
            cwd = Path.cwd()
            resolved_project_id = None
        else:
            raise LifecycleError(f"unsupported scope {scope!r}")

        resolved_source = source_path.expanduser().resolve()
        asset_name = name or resolved_source.name
        targets = resolve_targets(scope, platform_ids, cwd, self.os_name, self.env)
        if not targets:
            raise LifecycleError(f"no physical targets for platforms {platform_ids!r}")
        records: list[InstallTarget] = []
        for target in targets:
            record = InstallTarget(
                kind=kind,
                name=asset_name,
                scope=scope,
                project_id=resolved_project_id,
                version=None,
                target_id=target.target_id,
                path=target.path / asset_name,
                strategy="editable",
                consumers=target.consumers,
                source_path=resolved_source,
            )
            installed_record = self.installer.install(record, None)
            self.state.put(installed_record)
            records.append(installed_record)
        return InstallResult(tuple(records))

    def update(
        self,
        kind: str,
        name: str,
        *,
        scope: str,
    ) -> InstallResult:
        if scope != "global":
            raise LifecycleError("project update requires project_root and is not supported yet")
        records = self._records(kind, name, scope)
        if not records:
            raise LifecycleError(f"no installed targets for {kind} {name!r} in {scope}")
        platform_ids = sorted({consumer for record in records for consumer in record.consumers})
        method = records[0].strategy
        return self.install(
            kind,
            name,
            scope=scope,
            platform_ids=platform_ids,
            method=method,
        )

    def plan_update(self, kind: str, name: str, *, scope: str) -> UpdatePlan:
        records = self._records(kind, name, scope)
        latest = self.registry.resolve(kind, name)
        affected = {
            consumer
            for record in records
            if record.version != latest.version
            for consumer in record.consumers
        }
        path = records[0].path if records else None
        current_version = records[0].version if records else None
        return UpdatePlan(
            affected_consumers=affected,
            path=path,
            current_version=current_version,
            latest_version=latest.version,
        )

    def uninstall(
        self,
        kind: str,
        name: str,
        *,
        scope: str,
        platform_ids: list[str],
        project_root: Path | None = None,
    ) -> list[InstallTarget]:
        if scope == "project":
            if project_root is None:
                raise LifecycleError("project scope requires project_root")
            resolved_project_id = project_id(project_root)
        else:
            resolved_project_id = None
        records = self._records(kind, name, scope, resolved_project_id)
        updated_records: list[InstallTarget] = []
        requested = set(platform_ids)
        for record in records:
            consumers = requested & set(record.consumers)
            if not consumers:
                updated_records.append(record)
                continue
            updated = self.installer.uninstall(record, consumers)
            if updated.consumers:
                self.state.put(updated)
            else:
                self.state.remove(
                    kind,
                    name,
                    scope,
                    resolved_project_id,
                    record.target_id,
                )
            updated_records.append(updated)
        return updated_records

    def status(self) -> list[StatusReport]:
        return [
            StatusReport(record=record, healthy=self.installer.health(record))
            for record in self.state.all()
        ]

    def check(self):
        return self.registry.refresh()

    def doctor(self, fix: bool = False) -> list[StatusReport]:
        reports = self.status()
        if fix:
            for report in reports:
                if report.healthy or report.record.package_path is None:
                    continue
                self.installer.install(report.record, report.record.package_path)
            reports = self.status()
        return reports

    def prune_cache(self) -> list[Path]:
        referenced = {
            record.package_path.resolve()
            for record in self.state.all()
            if record.package_path is not None
        }
        removed: list[Path] = []
        for kind_dir in self.home.packages_path.iterdir():
            if not kind_dir.is_dir():
                continue
            for name_dir in kind_dir.iterdir():
                if not name_dir.is_dir():
                    continue
                for version_dir in name_dir.iterdir():
                    if version_dir.is_dir() and version_dir.resolve() not in referenced:
                        shutil.rmtree(version_dir)
                        removed.append(version_dir)
        return removed

    def _records(
        self,
        kind: str,
        name: str,
        scope: str,
        project_id_value: str | None = None,
    ) -> list[InstallTarget]:
        return [
            record
            for record in self.state.all()
            if record.kind == kind
            and record.name == name
            and record.scope == scope
            and (project_id_value is None or record.project_id == project_id_value)
        ]


def _current_os_name() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "windows"
    return "linux"
