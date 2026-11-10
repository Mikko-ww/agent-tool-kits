"""Platform-aware atkits command-line interface."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from atkits import __version__
from atkits.github import GitHubNetworkError, GitHubReleaseClient
from atkits.home import AtkitsHome
from atkits.installers import InstallConflict, Installer
from atkits.lifecycle import Lifecycle, LifecycleError
from atkits.models import Catalog, RegistryError
from atkits.packages import PackageStore
from atkits.platforms import load_registry
from atkits.registry import RegistryClient
from atkits.state import StateStore

app = typer.Typer(
    help="管理私有 GitHub Releases 中的版本化 agent 技能与插件。",
    rich_markup_mode="rich",
)
cache_app = typer.Typer(help="管理本地缓存。")
app.add_typer(cache_app, name="cache")

console = Console()
err = Console(stderr=True)


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


@dataclass
class Runtime:
    home: AtkitsHome
    registry: RegistryClient
    lifecycle: Lifecycle


def _current_os_name() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "windows"
    return "linux"


def _token_from_env() -> str | None:
    return (
        os.environ.get("ATKITS_GITHUB_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
    )


def _build_runtime() -> Runtime:
    home = AtkitsHome.discover()
    home.ensure_layout()
    config = home.load_config()
    repo = config.get("registry_repo")
    if not isinstance(repo, str) or not repo:
        raise LifecycleError("请先运行 atkits init 配置 registry")
    github = GitHubReleaseClient(repo, token=_token_from_env())
    registry = RegistryClient(home, github)
    package_store = PackageStore(home)
    installer = Installer(home)
    state = StateStore(home)
    lifecycle = Lifecycle(
        home,
        registry,
        package_store,
        installer,
        state,
        os_name=_current_os_name(),
        env=os.environ,
    )
    return Runtime(home=home, registry=registry, lifecycle=lifecycle)


def _short(path: Path) -> str:
    text = str(path)
    home = str(Path.home())
    return "~" + text[len(home) :] if text.startswith(home) else text


def _split_platforms(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


@app.command()
def init(
    registry: Annotated[str, typer.Option(help="GitHub 仓库，例如 owner/repo")],
) -> None:
    """初始化 ~/.atkits 并刷新远端 catalog。"""
    home = AtkitsHome.discover()
    home.ensure_layout()
    home.save_config({"registry_repo": registry})
    runtime = _build_runtime()
    try:
        runtime.lifecycle.check()
    except GitHubNetworkError as exc:
        err.print(f"[red]无法刷新 catalog：[/red]{exc}")
        raise typer.Exit(3) from exc
    console.print(f"[green]已初始化：[/green]{_short(home.path)}")


@app.command("list")
def list_cmd(
    remote: Annotated[bool, typer.Option("--remote", help="列出远端资产")] = False,
) -> None:
    """列出版本化资产。"""
    runtime = _build_runtime()
    try:
        if remote:
            catalog = runtime.lifecycle.check()
            _render_remote_catalog(catalog)
        else:
            reports = runtime.lifecycle.status()
            _render_status(reports)
    except GitHubNetworkError as exc:
        err.print(f"[red]网络错误：[/red]{exc}")
        raise typer.Exit(3) from exc
    except (LifecycleError, RegistryError) as exc:
        err.print(f"[red]错误：[/red]{exc}")
        raise typer.Exit(1) from exc


@app.command()
def check() -> None:
    """刷新远端 catalog 并显示资产列表。"""
    runtime = _build_runtime()
    try:
        catalog = runtime.lifecycle.check()
        _render_remote_catalog(catalog)
    except GitHubNetworkError as exc:
        err.print(f"[red]网络错误：[/red]{exc}")
        raise typer.Exit(3) from exc
    except (LifecycleError, RegistryError) as exc:
        err.print(f"[red]错误：[/red]{exc}")
        raise typer.Exit(1) from exc


@app.command()
def status() -> None:
    """检查本机安装健康状态。"""
    runtime = _build_runtime()
    reports = runtime.lifecycle.status()
    _render_status(reports)


@app.command()
def install(
    name: Annotated[str, typer.Argument(help="资产名，可写 name@version")],
    kind: Annotated[str, typer.Option(help="资产类型：skill/plugin")] = "skill",
    version: Annotated[Optional[str], typer.Option(help="指定版本")] = None,
    scope: Annotated[str, typer.Option(help="global/project")] = "global",
    platform: Annotated[Optional[str], typer.Option(help="平台，逗号分隔")] = None,
    method: Annotated[str, typer.Option(help="symlink/copy")] = "symlink",
    preset: Annotated[Optional[str], typer.Option(help="使用 catalog preset")] = None,
    all_platforms: Annotated[bool, typer.Option("--all", help="安装到所有平台")] = False,
    editable: Annotated[bool, typer.Option("--editable", help="链接到本地源码目录")] = False,
    no_input: Annotated[bool, typer.Option("--no-input", help="禁用交互")] = False,
    project_root: Annotated[Optional[Path], typer.Option(help="项目根目录")] = None,
) -> None:
    """安装或切换到指定版本。"""
    if "@" in name and version is None:
        name, parsed_version = name.rsplit("@", 1)
        version = parsed_version
    platform_ids = _split_platforms(platform)
    runtime = _build_runtime()
    if preset is not None:
        try:
            catalog = runtime.lifecycle.check()
            preset_data = catalog.preset(preset)
        except GitHubNetworkError as exc:
            err.print(f"[red]网络错误：[/red]{exc}")
            raise typer.Exit(3) from exc
        except RegistryError as exc:
            err.print(f"[red]preset 错误：[/red]{exc}")
            raise typer.Exit(2) from exc
        scope = preset_data.scope
        platform_ids = list(preset_data.platforms)
        method = preset_data.method
    if all_platforms:
        platform_ids = sorted(load_registry())
    if no_input and not platform_ids:
        err.print("[red]--no-input 需要同时提供 --platform、--preset 或 --all[/red]")
        raise typer.Exit(2)
    if not no_input and not platform_ids:
        answer = typer.prompt("请输入平台（逗号分隔）", default="")
        platform_ids = _split_platforms(answer)
        if not platform_ids:
            err.print("[red]必须选择至少一个平台[/red]")
            raise typer.Exit(2)
    try:
        if editable:
            source = Path(name).expanduser().resolve()
            if not source.is_dir() or not (source / "SKILL.md").is_file():
                err.print("[red]editable 源目录必须包含 SKILL.md[/red]")
                raise typer.Exit(2)
            result = runtime.lifecycle.install_editable(
                source,
                scope=scope,
                platform_ids=platform_ids or [],
                project_root=project_root,
            )
        else:
            result = runtime.lifecycle.install(
                kind,
                name,
                version,
                scope=scope,
                platform_ids=platform_ids or [],
                method=method,
                project_root=project_root,
            )
    except GitHubNetworkError as exc:
        err.print(f"[red]网络错误：[/red]{exc}")
        raise typer.Exit(3) from exc
    except (LifecycleError, InstallConflict, RegistryError) as exc:
        err.print(f"[red]安装失败：[/red]{exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]已安装：[/green]{kind} {name} {result.version} -> {_short(result.path)}")


@app.command()
def uninstall(
    name: Annotated[str, typer.Argument(help="资产名")],
    kind: Annotated[str, typer.Option(help="资产类型：skill/plugin")] = "skill",
    scope: Annotated[str, typer.Option(help="global/project")] = "global",
    platform: Annotated[Optional[str], typer.Option(help="平台，逗号分隔")] = None,
    project_root: Annotated[Optional[Path], typer.Option(help="项目根目录")] = None,
) -> None:
    """卸载指定平台上的资产。"""
    platform_ids = _split_platforms(platform)
    if not platform_ids:
        err.print("[red]请通过 --platform 指定要卸载的平台[/red]")
        raise typer.Exit(2)
    runtime = _build_runtime()
    try:
        runtime.lifecycle.uninstall(
            kind, name, scope=scope, platform_ids=platform_ids, project_root=project_root
        )
    except (LifecycleError, InstallConflict) as exc:
        err.print(f"[red]卸载失败：[/red]{exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]已卸载：[/green]{kind} {name} @ {scope}")


@app.command()
def update(
    name: Annotated[str, typer.Argument(help="资产名")],
    kind: Annotated[str, typer.Option(help="资产类型：skill/plugin")] = "skill",
    scope: Annotated[str, typer.Option(help="global/project")] = "global",
) -> None:
    """更新资产到最新稳定版本。"""
    runtime = _build_runtime()
    try:
        result = runtime.lifecycle.update(kind, name, scope=scope)
    except GitHubNetworkError as exc:
        err.print(f"[red]网络错误：[/red]{exc}")
        raise typer.Exit(3) from exc
    except (LifecycleError, InstallConflict, RegistryError) as exc:
        err.print(f"[red]更新失败：[/red]{exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]已更新：[/green]{kind} {name} -> {result.version}")


@app.command()
def doctor(
    fix: Annotated[bool, typer.Option("--fix", help="尝试修复受管目标")] = False,
) -> None:
    """检查并可选修复本地安装。"""
    runtime = _build_runtime()
    reports = runtime.lifecycle.doctor(fix=fix)
    _render_status(reports)


@cache_app.command("prune")
def cache_prune() -> None:
    """清理未被安装记录引用的版本包。"""
    runtime = _build_runtime()
    removed = runtime.lifecycle.prune_cache()
    console.print(f"[green]已清理 {len(removed)} 个版本包[/green]")


@app.command()
def platforms() -> None:
    """列出已知逻辑平台。"""
    registry = load_registry()
    table = Table(title="平台")
    table.add_column("id")
    table.add_column("名称")
    table.add_column("项目路径")
    table.add_column("全局路径")
    for platform in registry.values():
        project = ", ".join(f"{spec.id}:{spec.template}" for spec in platform.project_paths)
        global_paths = ", ".join(f"{spec.id}:{spec.template}" for spec in platform.global_paths)
        table.add_row(platform.id, platform.display_name, project, global_paths)
    console.print(table)


def _render_remote_catalog(catalog: Catalog) -> None:
    table = Table(title="远端资产")
    table.add_column("类型")
    table.add_column("名称")
    table.add_column("最新稳定版")
    for kind in ("skill", "plugin", "cli"):
        for name in catalog.names(kind):
            latest = catalog.latest(kind, name)
            table.add_row(kind, name, latest.version)
    for name, entry in catalog.external_skills().items():
        source = entry.get("source", "-")
        table.add_row("external", name, str(source))
    console.print(table)
    presets = catalog.presets()
    if presets:
        preset_table = Table(title="远端 presets")
        preset_table.add_column("名称")
        preset_table.add_column("范围")
        preset_table.add_column("平台")
        preset_table.add_column("方法")
        for preset in presets.values():
            preset_table.add_row(
                preset.name,
                preset.scope,
                ",".join(preset.platforms),
                preset.method,
            )
        console.print(preset_table)


def _render_status(reports: list[object]) -> None:
    table = Table(title="本机安装")
    table.add_column("类型")
    table.add_column("名称")
    table.add_column("版本")
    table.add_column("路径")
    table.add_column("平台")
    table.add_column("状态")
    for report in reports:
        record = report.record
        status = "[green]ok[/green]" if report.healthy else "[red]broken[/red]"
        table.add_row(
            record.kind,
            record.name,
            record.version or "-",
            _short(record.path),
            ",".join(record.consumers),
            status,
        )
    console.print(table)


if __name__ == "__main__":
    app()
