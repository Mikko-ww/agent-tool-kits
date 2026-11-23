"""Platform-aware atkits command-line interface."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import questionary
import typer
from rich.console import Console
from rich.table import Table

from atkits import __version__
from atkits.external import ExternalError, ExternalInstaller
from atkits.github import GitHubError, GitHubNetworkError, GitHubReleaseClient
from atkits.home import AtkitsHome
from atkits.installers import InstallConflict, Installer
from atkits.lifecycle import Lifecycle, LifecycleError, StatusReport
from atkits.models import Catalog, RegistryError
from atkits.packages import PackageError, PackageStore
from atkits.platforms import (
    PlatformDefinition,
    PlatformError,
    load_registry,
    normalize_platform_ids,
)
from atkits.registry import RegistryClient
from atkits.self_update import SelfUpdateError
from atkits.self_update import self_update as run_self_update
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
    package_store = PackageStore(home, download_asset=github.download_asset)
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


def _has_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM") != "dumb"


def _prompt_platforms(registry: Mapping[str, PlatformDefinition]) -> list[str]:
    choices = [
        questionary.Choice(f"{definition.display_name} ({platform_id})", value=platform_id)
        for platform_id, definition in registry.items()
    ]
    try:
        return questionary.checkbox(
            "选择安装平台（至少一项）",
            choices=choices,
            instruction="键入名称或 ID 搜索 · ↑/↓ 移动 · 空格勾选 · 回车确认 · Ctrl+C 取消",
            validate=lambda values: bool(values) or "请至少选择一个平台",
            use_jk_keys=False,
            use_emacs_keys=False,
            use_search_filter=True,
        ).unsafe_ask()
    except (KeyboardInterrupt, EOFError):
        typer.echo("已取消安装。", err=True)
        raise typer.Exit(130) from None


def _prompt_install_method() -> str:
    try:
        return questionary.select(
            "选择安装方式",
            choices=[
                questionary.Choice("copy（推荐；不需要创建符号链接的权限）", value="copy"),
                questionary.Choice("symlink（需要创建符号链接的权限）", value="symlink"),
            ],
            default="copy",
            instruction="↑/↓ 移动 · 回车确认 · Ctrl+C 取消",
        ).unsafe_ask()
    except (KeyboardInterrupt, EOFError):
        typer.echo("已取消安装。", err=True)
        raise typer.Exit(130) from None


def _select_install_platforms(
    platform_ids: list[str] | None, *, no_input: bool, all_platforms: bool
) -> list[str]:
    registry = load_registry()
    if all_platforms:
        platform_ids = sorted(registry)
    if not platform_ids:
        if no_input or not _has_interactive_terminal():
            typer.echo("非交互安装需要提供 --platform、--preset 或 --all。", err=True)
            raise typer.Exit(2)
        if not registry:
            raise PlatformError("平台注册表没有可选平台")
        platform_ids = _prompt_platforms(registry)

    platform_ids = normalize_platform_ids(platform_ids)
    unknown = [item for item in platform_ids if item not in registry]
    if unknown:
        typer.echo("未知平台：" + "、".join(map(repr, unknown)), err=True)
        typer.echo("可用平台 ID：" + ", ".join(registry), err=True)
        raise typer.Exit(2)
    return platform_ids


def _catalog_for_runtime(runtime: Runtime) -> Catalog:
    try:
        return runtime.registry.cached()
    except (AttributeError, RegistryError):
        return runtime.lifecycle.check()


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
    details: Annotated[bool, typer.Option("--details", help="按安装路径列出本机明细")] = False,
) -> None:
    """汇总本机安装，也可查看路径明细或远端资产。"""
    if remote and details:
        raise typer.BadParameter("--details 只适用于本机安装，不能与 --remote 同用")

    try:
        runtime = _build_runtime()
        if remote:
            catalog = runtime.lifecycle.check()
            _render_remote_catalog(catalog)
        else:
            reports = runtime.lifecycle.status()
            if details:
                _render_status(reports)
            else:
                _render_install_summary(reports)
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
    version: Annotated[str | None, typer.Option(help="指定版本")] = None,
    scope: Annotated[str, typer.Option(help="global/project")] = "global",
    platform: Annotated[str | None, typer.Option(help="平台，逗号分隔")] = None,
    method: Annotated[
        str | None, typer.Option(help="symlink/copy；默认 symlink，Windows 交互时可选择")
    ] = None,
    preset: Annotated[str | None, typer.Option(help="使用 catalog preset")] = None,
    all_platforms: Annotated[bool, typer.Option("--all", help="安装到所有平台")] = False,
    editable: Annotated[bool, typer.Option("--editable", help="链接到本地源码目录")] = False,
    no_input: Annotated[bool, typer.Option("--no-input", help="禁用交互")] = False,
    project_root: Annotated[Path | None, typer.Option(help="项目根目录")] = None,
) -> None:
    """安装或切换到指定版本。"""
    if "@" in name and version is None:
        name, parsed_version = name.rsplit("@", 1)
        version = parsed_version
    os_name = _current_os_name()
    platform_ids = _split_platforms(platform)
    try:
        runtime = _build_runtime()
        catalog = _catalog_for_runtime(runtime)
    except GitHubNetworkError as exc:
        err.print(f"[red]网络错误：[/red]{exc}")
        raise typer.Exit(3) from exc
    except (LifecycleError, RegistryError) as exc:
        err.print(f"[red]catalog 错误：[/red]{exc}")
        raise typer.Exit(1) from exc
    if preset is not None:
        try:
            preset_data = catalog.preset(preset)
        except GitHubNetworkError as exc:
            err.print(f"[red]网络错误：[/red]{exc}")
            raise typer.Exit(3) from exc
        except RegistryError as exc:
            err.print(f"[red]preset 错误：[/red]{exc}")
            raise typer.Exit(2) from exc
        scope = preset_data.scope
        platform_ids = list(preset_data.platforms)
        if os_name != "windows" or method is None:
            method = preset_data.method
    try:
        platform_ids = _select_install_platforms(
            platform_ids, no_input=no_input, all_platforms=all_platforms
        )
    except PlatformError as exc:
        typer.echo(f"平台错误：{exc}", err=True)
        raise typer.Exit(2) from exc

    if not editable and name in catalog.external_skills():
        home = runtime.home.path if hasattr(runtime.home, "path") else runtime.home
        try:
            external = ExternalInstaller(
                catalog,
                home,
                os_name=os_name,
                env=os.environ,
            ).install(name, platform_ids)
        except (ExternalError, PlatformError) as exc:
            err.print(f"[red]外部技能安装失败：[/red]{exc}")
            raise typer.Exit(1) from exc
        console.print(
            f"[green]已安装外部技能：[/green]{name} -> {_short(external.path)}"
            if external.path
            else f"[green]已安装外部技能：[/green]{name}"
        )
        return
    try:
        if editable:
            source = Path(name).expanduser().resolve()
            if not source.is_dir() or not (source / "SKILL.md").is_file():
                err.print("[red]editable 源目录必须包含 SKILL.md[/red]")
                raise typer.Exit(2)
            result = runtime.lifecycle.install_editable(
                source,
                scope=scope,
                platform_ids=platform_ids,
                project_root=project_root,
            )
        else:
            if method is None:
                if os_name == "windows" and not no_input and _has_interactive_terminal():
                    method = _prompt_install_method()
                else:
                    method = "symlink"
            result = runtime.lifecycle.install(
                kind,
                name,
                version,
                scope=scope,
                platform_ids=platform_ids,
                method=method,
                project_root=project_root,
            )
    except GitHubNetworkError as exc:
        err.print(f"[red]网络错误：[/red]{exc}")
        raise typer.Exit(3) from exc
    except (
        LifecycleError,
        InstallConflict,
        PlatformError,
        RegistryError,
        PackageError,
        GitHubError,
    ) as exc:
        err.print(f"[red]安装失败：[/red]{exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]已安装：[/green]{kind} {name} {result.version} -> {_short(result.path)}")


@app.command()
def uninstall(
    name: Annotated[str, typer.Argument(help="资产名")],
    kind: Annotated[str, typer.Option(help="资产类型：skill/plugin")] = "skill",
    scope: Annotated[str, typer.Option(help="global/project")] = "global",
    platform: Annotated[str | None, typer.Option(help="平台，逗号分隔")] = None,
    project_root: Annotated[Path | None, typer.Option(help="项目根目录")] = None,
) -> None:
    """卸载指定平台上的资产。"""
    platform_ids = _split_platforms(platform)
    if not platform_ids:
        err.print("[red]请通过 --platform 指定要卸载的平台[/red]")
        raise typer.Exit(2)
    runtime = _build_runtime()
    try:
        runtime.lifecycle.uninstall(
            kind,
            name,
            scope=scope,
            platform_ids=normalize_platform_ids(platform_ids),
            project_root=project_root,
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
    except (LifecycleError, InstallConflict, RegistryError, PackageError, GitHubError) as exc:
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


@app.command("self-update")
def self_update_cmd() -> None:
    """更新 atkits CLI 到最新 wheel。"""
    try:
        runtime = _build_runtime()

        def downloader(asset, destination: Path) -> None:
            runtime.registry.github.download_asset(asset.asset_id, destination)

        catalog = runtime.lifecycle.check()
        version = run_self_update(uv_executable="uv", registry=catalog, downloader=downloader)
    except GitHubNetworkError as exc:
        err.print(f"[red]网络错误：[/red]{exc}")
        raise typer.Exit(3) from exc
    except (SelfUpdateError, LifecycleError, RegistryError, GitHubError) as exc:
        err.print(f"[red]自更新失败：[/red]{exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]已更新 atkits：[/green]{version}")


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
                ",".join(normalize_platform_ids(preset.platforms)),
                preset.method,
            )
        console.print(preset_table)


def _status_label(healthy: bool) -> str:
    return "[green]ok[/green]" if healthy else "[red]broken[/red]"


def _render_install_summary(reports: list[StatusReport]) -> None:
    groups: dict[tuple[str, str, str | None, bool], list[str]] = {}
    for report in reports:
        record = report.record
        group = (record.kind, record.name, record.version, report.healthy)
        groups.setdefault(group, []).extend(record.consumers)

    table = Table(title="本机安装汇总")
    table.add_column("类型")
    table.add_column("名称")
    table.add_column("版本")
    table.add_column("平台", overflow="fold")
    table.add_column("状态")
    for (kind, name, version, healthy), platforms in groups.items():
        table.add_row(
            kind,
            name,
            version or "-",
            ", ".join(normalize_platform_ids(platforms)),
            _status_label(healthy),
        )
    console.print(table)


def _render_status(reports: list[StatusReport]) -> None:
    table = Table(title="本机安装")
    table.add_column("类型")
    table.add_column("名称")
    table.add_column("版本")
    table.add_column("路径")
    table.add_column("平台")
    table.add_column("状态")
    for report in reports:
        record = report.record
        table.add_row(
            record.kind,
            record.name,
            record.version or "-",
            _short(record.path),
            ",".join(record.consumers),
            _status_label(report.healthy),
        )
    console.print(table)


if __name__ == "__main__":
    app()
