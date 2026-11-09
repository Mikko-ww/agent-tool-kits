"""atkits 命令行入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, engine, platforms
from .engine import State
from .importer import discover_skill_dirs, import_skill
from .profile import Profile, ProfileError, resolve_profile_path
from .vault import Vault, find_root

app = typer.Typer(
    help="一个金库管理所有 agent 技能，按清单嫁接到 Claude Code、Codex、Cursor、pi 等平台。",
    rich_markup_mode="rich",
)
console = Console()
err = Console(stderr=True)

_STATE_STYLE = {
    State.OK: "green",
    State.LINK: "cyan",
    State.RELINK: "yellow",
    State.ADOPT: "cyan",
    State.COPY: "cyan",
    State.SYNC: "yellow",
    State.CONFLICT: "red",
    State.EXTERNAL_MISSING: "magenta",
    State.ORPHAN: "yellow",
    State.NOT_IN_VAULT: "red",
    State.ERROR: "red",
}

ProfileArg = Annotated[
    str,
    typer.Argument(help="'global'、项目清单名（profiles/projects/<name>.yaml）或清单文件路径"),
]


def _load(profile_name: str) -> tuple[Vault, Profile]:
    vault = Vault(find_root())
    try:
        profile = Profile.load(resolve_profile_path(vault.root, profile_name))
    except (ProfileError, KeyError) as exc:
        err.print(f"[red]错误：[/red]{exc}")
        raise typer.Exit(2)
    return vault, profile


def _short(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home) :] if text.startswith(home) else text


def _render(report: engine.Report, *, title: str, verbose: bool) -> None:
    table = Table(title=title, show_lines=False, expand=True)
    table.add_column("资产", overflow="fold")
    table.add_column("平台")
    table.add_column("状态")
    table.add_column("位置", overflow="fold")
    table.add_column("说明", overflow="fold")
    for action in sorted(report.actions, key=lambda a: (a.kind, a.skill, a.platform)):
        if action.state is State.OK and not verbose:
            continue
        style = _STATE_STYLE[action.state]
        table.add_row(
            f"[dim]插件[/dim] {action.skill}" if action.is_plugin else action.skill,
            action.platform,
            f"[{style}]{action.state.value}[/{style}]",
            _short(action.link),
            action.note or (action.source or ""),
        )
    if table.row_count:
        console.print(table)
    ok = len(report.by_state(State.OK))
    console.print(f"[green]{ok} ok[/green]", end="")
    for state in State:
        if state is State.OK:
            continue
        n = len(report.by_state(state))
        if n:
            console.print(
                f" · [{_STATE_STYLE[state]}]{n} {state.value}[/{_STATE_STYLE[state]}]", end=""
            )
    console.print()


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", is_eager=True, help="显示版本")] = False,
) -> None:
    if version:
        console.print(f"atkits {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def status(
    profile: ProfileArg = "global",
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="同时列出 ok 的行")] = False,
) -> None:
    """对比清单与磁盘实际状态，不做任何修改。"""
    vault, prof = _load(profile)
    report = engine.plan(vault, prof)
    _render(report, title=f"atkits status · {prof.path.name}", verbose=verbose)
    raise typer.Exit(1 if report.needs_work else 0)


@app.command()
def apply(
    profile: ProfileArg = "global",
    dry_run: Annotated[bool, typer.Option("-n", "--dry-run", help="只展示计划，不动文件")] = False,
    force: Annotated[
        bool, typer.Option("--force", help="备份有冲突的真实目录后重新建链 / 重新拷贝")
    ] = False,
    prune: Annotated[
        bool,
        typer.Option("--prune", help="清理清单里没有的金库 symlink 与插件拷贝（真实目录走备份）"),
    ] = False,
    no_external: Annotated[
        bool, typer.Option("--no-external", help="跳过外部技能（不调用 `npx skills add`）")
    ] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="同时列出 ok 的行")] = False,
) -> None:
    """让文件系统与清单一致（幂等，可重复执行）。"""
    vault, prof = _load(profile)
    try:
        report = engine.apply(
            vault, prof, dry_run=dry_run, force=force, prune=prune, skip_external=no_external
        )
    except engine.external.ExternalError as exc:
        err.print(f"[red]外部技能安装失败：[/red]{exc}")
        raise typer.Exit(1)
    label = "预演" if dry_run else "已执行"
    _render(report, title=f"atkits apply（{label}）· {prof.path.name}", verbose=verbose)
    for cmd in report.external_commands:
        prefix = "[magenta]将执行[/magenta]" if dry_run else "[magenta]已执行[/magenta]"
        console.print(f"{prefix}：{' '.join(cmd)}")
    conflicts = report.by_state(State.CONFLICT)
    if conflicts and not force:
        err.print(f"[red]{len(conflicts)} 处冲突[/red] —— 请先检查，确认后加 --force 重跑")
        raise typer.Exit(1)
    if report.by_state(State.NOT_IN_VAULT, State.ERROR):
        raise typer.Exit(1)


@app.command("import")
def import_(
    paths: Annotated[list[Path], typer.Argument(help="技能目录，或包含多个技能的目录")],
    profile: Annotated[str, typer.Option("-p", "--profile", help="写入哪个清单")] = "global",
    source: Annotated[
        Optional[str], typer.Option("--source", help="按外部技能记录，例如 openai/skills")
    ] = None,
    to: Annotated[
        Optional[str], typer.Option("--to", help="目标平台，逗号分隔；默认按路径推断")
    ] = None,
    rename: Annotated[Optional[str], typer.Option("--rename", help="以新名字存入金库")] = None,
    dry_run: Annotated[bool, typer.Option("-n", "--dry-run", help="只展示，不动文件")] = False,
) -> None:
    """把散落在 ~/.codex/skills、~/.agents/skills 等处的技能收编进金库和清单。"""
    vault, prof = _load(profile)
    targets = [t.strip() for t in to.split(",")] if to else None
    skill_dirs = [d for p in paths for d in discover_skill_dirs(p)]
    if not skill_dirs:
        err.print("[red]给定路径下没有找到 SKILL.md[/red]")
        raise typer.Exit(1)
    if rename and len(skill_dirs) > 1:
        err.print("[red]--rename 只能用于单个技能[/red]")
        raise typer.Exit(2)

    table = Table(title=f"atkits import{'（预演）' if dry_run else ''}")
    table.add_column("路径")
    table.add_column("名称")
    table.add_column("结果")
    table.add_column("说明")
    for skill_dir in skill_dirs:
        result = import_skill(
            vault, prof, skill_dir, source=source, to=targets, rename=rename, dry_run=dry_run
        )
        style = {"conflict": "red", "skipped": "yellow"}.get(result.outcome, "green")
        table.add_row(
            _short(result.path), result.name, f"[{style}]{result.outcome}[/{style}]", result.detail
        )
    console.print(table)
    if not dry_run:
        console.print(f"清单已更新：{_short(prof.path)} —— 接下来运行 [bold]atkits apply[/bold]")


@app.command("platforms")
def platforms_cmd() -> None:
    """列出已知平台及其读取全局技能的目录。"""
    table = Table(title="平台")
    table.add_column("id")
    table.add_column("名称")
    table.add_column("项目级目录")
    table.add_column("全局目录")
    table.add_column("已存在")
    table.add_column("本地插件目录")
    for p in platforms.PLATFORMS.values():
        g = p.global_skills_dir()
        table.add_row(
            p.id,
            p.label,
            p.project_skills_dir,
            _short(g),
            "是" if g.is_dir() else "-",
            _short(p.plugins_dir()) if p.supports_plugins else "-",
        )
    console.print(table)


@app.command("skills")
def skills_cmd() -> None:
    """列出金库中的技能。"""
    vault = Vault(find_root())
    table = Table(title=f"金库技能 · {_short(vault.skills_dir)}")
    table.add_column("目录")
    table.add_column("frontmatter 名称（与目录不同时显示）")
    for dir_name, skill in vault.skills().items():
        table.add_row(dir_name, skill.name if skill.name != dir_name else "")
    console.print(table)


@app.command("plugins")
def plugins_cmd() -> None:
    """列出金库中的插件（plugins/<name>/plugin.yaml）。"""
    vault = Vault(find_root())
    table = Table(title=f"金库插件 · {_short(vault.plugins_dir)}")
    table.add_column("目录")
    table.add_column("plugin.yaml 名称（与目录不同时显示）")
    table.add_column("技能数")
    for dir_name, plugin in vault.plugins().items():
        skills_dir = plugin.path / "skills"
        n = (
            sum(1 for d in skills_dir.iterdir() if (d / "SKILL.md").is_file())
            if skills_dir.is_dir()
            else 0
        )
        table.add_row(dir_name, plugin.name if plugin.name != dir_name else "", str(n))
    console.print(table)


if __name__ == "__main__":
    app()
