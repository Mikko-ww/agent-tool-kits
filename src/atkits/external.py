"""Delegate external skill favorites to the vercel skills CLI."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atkits.models import Catalog
from atkits.platforms import load_registry, resolve_targets


class ExternalError(RuntimeError):
    """Raised when an external skill cannot be installed or verified."""


@dataclass(frozen=True)
class ExternalHealth:
    installed: bool
    path: Path | None


CommandRunner = Callable[[str, str, list[str]], None]


class ExternalInstaller:
    """Install and verify external skills listed in the remote catalog."""

    def __init__(
        self,
        catalog: Catalog | Mapping[str, Any],
        home: Path,
        *,
        os_name: str,
        env: Mapping[str, str],
        command_runner: CommandRunner | None = None,
    ) -> None:
        if isinstance(catalog, Catalog):
            self.external_skills = catalog.external_skills()
        else:
            raw = catalog.get("external_skills") or {}
            if not isinstance(raw, Mapping):
                raise ExternalError("external_skills must be a mapping")
            self.external_skills = dict(raw)
        self.home = home
        self.os_name = os_name
        self.env = dict(env)
        self.command_runner = command_runner or _default_command_runner

    def install(self, name: str, platform_ids: list[str]) -> ExternalHealth:
        entry = self.external_skills.get(name)
        if not isinstance(entry, Mapping):
            raise ExternalError(f"unknown external skill {name!r}")
        source = entry.get("source")
        if not isinstance(source, str) or not source:
            raise ExternalError(f"external skill {name!r} has no source")
        if not platform_ids:
            raise ExternalError("external skill install requires at least one platform")

        self.command_runner(source, name, platform_ids)
        health = self.health(name, platform_ids=platform_ids)
        if not health.installed:
            raise ExternalError(f"external skill {name!r} is not installed after runner")
        return health

    def health(
        self,
        name: str,
        *,
        platform_ids: list[str] | None = None,
        paths: list[Path] | None = None,
    ) -> ExternalHealth:
        candidates = paths if paths is not None else self._candidate_paths(name, platform_ids)
        for path in candidates:
            if path.is_symlink() and not path.exists():
                continue
            if path.is_dir() and (path / "SKILL.md").is_file():
                return ExternalHealth(installed=True, path=path)
        return ExternalHealth(installed=False, path=candidates[0] if candidates else None)

    def _candidate_paths(self, name: str, platform_ids: list[str] | None) -> list[Path]:
        selected = platform_ids or sorted(load_registry())
        targets = resolve_targets("global", selected, Path.cwd(), self.os_name, self.env)
        return [target.path / name for target in targets]


def _default_command_runner(source: str, name: str, platform_ids: list[str]) -> None:
    run_add(
        source,
        [name],
        platform_ids,
        global_scope=True,
        cwd=None,
        dry_run=False,
    )


def skills_cli_available() -> bool:
    return shutil.which("npx") is not None


def build_add_command(
    source: str, skill_names: list[str], agents: list[str], *, global_scope: bool
) -> list[str]:
    cmd = ["npx", "-y", "skills@latest", "add", source]
    for name in skill_names:
        cmd += ["--skill", name]
    for agent in agents:
        cmd += ["--agent", agent]
    if global_scope:
        cmd.append("--global")
    cmd.append("--yes")
    return cmd


def run_add(
    source: str,
    skill_names: list[str],
    agents: list[str],
    *,
    global_scope: bool,
    cwd: Path | None,
    dry_run: bool,
) -> list[str]:
    cmd = build_add_command(source, skill_names, agents, global_scope=global_scope)
    if dry_run:
        return cmd
    if not skills_cli_available():
        raise ExternalError("找不到 `npx`；管理外部技能需要安装 Node.js")
    result = subprocess.run(cmd, cwd=cwd, check=False)
    if result.returncode != 0:
        raise ExternalError(f"`{' '.join(cmd)}` 退出码 {result.returncode}")
    return cmd
