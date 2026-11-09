"""计划与执行：把清单和文件系统做对比，并修正差异。

刻意设计为无状态，不需要 lock 文件就能检测漂移和孤儿：

- 技能：一个链接“被 atkits 管理”当且仅当它是 symlink 且解析后落在金库的 `skills/` 内。
- 插件：Cursor 的本地插件目录拒绝指向目录外的 symlink，所以走**拷贝同步**。
  “被管理”的判定退化为：目标是真实目录，且目录名对应金库 `plugins/` 里的一个插件；
  内容与金库逐文件比较决定 ok / sync。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import external, fsutil, platforms
from .profile import PluginSpec, Profile, SkillSpec
from .vault import Vault

KIND_SKILL = "skill"
KIND_PLUGIN = "plugin"


class State(str, Enum):
    OK = "ok"  # already linked / copy up to date / external already present
    LINK = "link"  # nothing there yet -> create symlink
    RELINK = "relink"  # symlink exists but points elsewhere / is broken
    ADOPT = "adopt"  # real copy identical to vault -> swap for symlink (safe)
    COPY = "copy"  # (plugin) nothing usable there yet -> copy from vault
    SYNC = "sync"  # (plugin) copy exists but differs from vault -> backup, re-copy
    CONFLICT = "conflict"  # real copy differs from vault -> needs --force
    EXTERNAL_MISSING = "external-missing"  # delegate to `npx skills add`
    ORPHAN = "orphan"  # managed by atkits but no longer declared in profile
    NOT_IN_VAULT = "not-in-vault"  # profile names a vault skill/plugin that does not exist
    ERROR = "error"  # filesystem operation failed (permissions, ...)


@dataclass
class Action:
    state: State
    skill: str  # asset name (skill or plugin)
    platform: str
    link: Path  # where the asset lives on the platform (symlink or real copy)
    target: Path | None = None
    source: str | None = None
    note: str = ""
    kind: str = KIND_SKILL

    @property
    def is_plugin(self) -> bool:
        return self.kind == KIND_PLUGIN


@dataclass
class Report:
    actions: list[Action] = field(default_factory=list)
    external_commands: list[list[str]] = field(default_factory=list)

    def by_state(self, *states: State) -> list[Action]:
        return [a for a in self.actions if a.state in states]

    @property
    def needs_work(self) -> bool:
        return any(a.state is not State.OK for a in self.actions)


def _scope_dir(platform_id: str, project: Path | None) -> Path:
    return platforms.get(platform_id).skills_dir(project)


def plan(vault: Vault, profile: Profile) -> Report:
    report = Report()
    vault_skills = vault.skills()
    project = profile.project
    declared: dict[str, set[str]] = defaultdict(set)  # platform -> skill names

    for spec in profile.skills.values():
        for platform_id in spec.to:
            declared[platform_id].add(spec.name)
            link = _scope_dir(platform_id, project) / spec.name
            if spec.is_external:
                report.actions.append(_plan_external(spec, platform_id, link))
            else:
                report.actions.append(_plan_vault(spec, platform_id, link, vault_skills))

    for platform_id in profile.targets:
        base = _scope_dir(platform_id, project)
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_symlink() or not vault.contains(entry):
                continue
            if entry.name in declared[platform_id]:
                continue
            report.actions.append(
                Action(State.ORPHAN, entry.name, platform_id, entry, note="清单中未声明")
            )

    _plan_plugins(vault, profile, report)
    return report


def _plan_plugins(vault: Vault, profile: Profile, report: Report) -> None:
    vault_plugins = vault.plugins()
    declared: dict[str, set[str]] = defaultdict(set)

    for spec in profile.plugins.values():
        for platform_id in spec.to:
            declared[platform_id].add(spec.name)
            dest = platforms.get(platform_id).plugins_dir() / spec.name
            report.actions.append(_plan_plugin(spec, platform_id, dest, vault, vault_plugins))

    for platform_id in profile.targets:
        platform = platforms.get(platform_id)
        if not platform.supports_plugins:
            continue
        base = platform.plugins_dir()
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.name.startswith(".") or entry.name in declared[platform_id]:
                continue
            if entry.is_symlink():
                if not vault.contains_plugin(entry):
                    continue
                note = "清单中未声明（指向金库的 symlink）"
            elif entry.is_dir() and entry.name in vault_plugins:
                note = "清单中未声明（与金库插件同名的拷贝，--prune 时备份）"
            else:
                continue
            report.actions.append(
                Action(State.ORPHAN, entry.name, platform_id, entry, note=note, kind=KIND_PLUGIN)
            )


def _plan_plugin(
    spec: PluginSpec, platform_id: str, dest: Path, vault: Vault, vault_plugins
) -> Action:
    plugin = vault_plugins.get(spec.name)
    if plugin is None:
        return Action(
            State.NOT_IN_VAULT,
            spec.name,
            platform_id,
            dest,
            note="金库 plugins/ 中不存在",
            kind=KIND_PLUGIN,
        )
    target = plugin.path
    if dest.is_symlink():
        # Cursor 会拒绝任何指向 plugins/local 之外的 symlink，所以链接一律要换成拷贝。
        if vault.contains_plugin(dest) or not dest.exists():
            return Action(
                State.COPY,
                spec.name,
                platform_id,
                dest,
                target,
                note=f"替换无效的 symlink（{_describe(dest)}）",
                kind=KIND_PLUGIN,
            )
        return Action(
            State.CONFLICT,
            spec.name,
            platform_id,
            dest,
            target,
            note=f"symlink 指向金库之外：{_describe(dest)}",
            kind=KIND_PLUGIN,
        )
    if dest.exists():
        if dest.is_dir() and fsutil.dirs_equal(dest, target):
            return Action(State.OK, spec.name, platform_id, dest, target, kind=KIND_PLUGIN)
        if dest.is_dir():
            return Action(
                State.SYNC,
                spec.name,
                platform_id,
                dest,
                target,
                note="拷贝与金库内容不同，将备份后重新拷贝",
                kind=KIND_PLUGIN,
            )
        return Action(
            State.CONFLICT,
            spec.name,
            platform_id,
            dest,
            target,
            note="目标是普通文件",
            kind=KIND_PLUGIN,
        )
    return Action(State.COPY, spec.name, platform_id, dest, target, kind=KIND_PLUGIN)


def _plan_vault(spec: SkillSpec, platform_id: str, link: Path, vault_skills) -> Action:
    skill = vault_skills.get(spec.name)
    if skill is None:
        return Action(
            State.NOT_IN_VAULT, spec.name, platform_id, link, note="金库 skills/ 中不存在"
        )
    target = skill.path
    if link.is_symlink():
        if fsutil.points_to(link, target):
            return Action(State.OK, spec.name, platform_id, link, target)
        return Action(State.RELINK, spec.name, platform_id, link, target, note=_describe(link))
    if link.exists():
        if link.is_dir() and fsutil.dirs_equal(link, target):
            return Action(
                State.ADOPT, spec.name, platform_id, link, target, note="内容与金库一致的真实目录"
            )
        return Action(
            State.CONFLICT, spec.name, platform_id, link, target, note="真实目录，内容与金库不同"
        )
    return Action(State.LINK, spec.name, platform_id, link, target)


def _plan_external(spec: SkillSpec, platform_id: str, link: Path) -> Action:
    if link.exists() or link.is_symlink():
        return Action(State.OK, spec.name, platform_id, link, source=spec.source)
    return Action(State.EXTERNAL_MISSING, spec.name, platform_id, link, source=spec.source)


def _describe(link: Path) -> str:
    try:
        return f"当前指向 {link.readlink()}"
    except OSError:
        return "断链"


def _execute(action: Action, *, dry_run: bool, force: bool, prune: bool) -> None:
    if action.is_plugin:
        _execute_plugin(action, dry_run=dry_run, force=force, prune=prune)
        return
    if action.state in (State.LINK, State.RELINK, State.ADOPT):
        if dry_run:
            return
        if action.state is State.ADOPT:
            fsutil.backup(action.link, action.platform)
        fsutil.make_symlink(action.link, action.target)  # type: ignore[arg-type]
    elif action.state is State.CONFLICT and force:
        if dry_run:
            action.note = "将备份后重新建链（--force）"
            return
        moved = fsutil.backup(action.link, action.platform)
        action.note = f"已备份到 {moved}"
        fsutil.make_symlink(action.link, action.target)  # type: ignore[arg-type]
    elif action.state is State.ORPHAN and prune:
        if not dry_run:
            action.link.unlink()
        action.note = "已删除"


def _execute_plugin(action: Action, *, dry_run: bool, force: bool, prune: bool) -> None:
    """插件只做拷贝：symlink 直接 unlink，真实目录一律先备份。"""
    label = f"{action.platform}-plugins"
    if action.state is State.COPY:
        if dry_run:
            return
        if action.link.is_symlink():
            action.link.unlink()
        fsutil.copy_tree(action.target, action.link)  # type: ignore[arg-type]
    elif action.state is State.SYNC:
        if dry_run:
            return
        moved = fsutil.backup(action.link, label)
        fsutil.copy_tree(action.target, action.link)  # type: ignore[arg-type]
        action.note = f"已重新拷贝；旧副本备份到 {moved}"
    elif action.state is State.CONFLICT and force:
        if dry_run:
            action.note = "将备份后重新拷贝（--force）"
            return
        moved = fsutil.remove_link_or_backup(action.link, label)
        fsutil.copy_tree(action.target, action.link)  # type: ignore[arg-type]
        action.note = f"已备份到 {moved}" if moved else "已移除 symlink 并拷贝"
    elif action.state is State.ORPHAN and prune:
        if dry_run:
            action.note = "将删除 symlink / 备份真实目录（--prune）"
            return
        moved = fsutil.remove_link_or_backup(action.link, label)
        action.note = f"已备份到 {moved}" if moved else "已删除"


def apply(
    vault: Vault,
    profile: Profile,
    *,
    dry_run: bool = False,
    force: bool = False,
    prune: bool = False,
    skip_external: bool = False,
) -> Report:
    report = plan(vault, profile)
    project = profile.project

    for action in report.actions:
        try:
            _execute(action, dry_run=dry_run, force=force, prune=prune)
        except OSError as exc:
            action.state = State.ERROR
            action.note = f"{exc.strerror or exc}: {exc.filename or action.link}"

    if not skip_external:
        grouped: dict[tuple[str, str], set[str]] = defaultdict(set)  # (source, skill) -> agents
        for action in report.by_state(State.EXTERNAL_MISSING):
            grouped[(action.source or "", action.skill)].add(action.platform)
        for (source, skill), agents in sorted(grouped.items()):
            cmd = external.run_add(
                source,
                [skill],
                sorted(agents),
                global_scope=project is None,
                cwd=project,
                dry_run=dry_run,
            )
            report.external_commands.append(cmd)
    return report
