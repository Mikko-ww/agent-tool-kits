import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.text import Text
from typer.testing import CliRunner

import atkits.cli as cli_module
import atkits.self_update as self_update_module
from atkits.cli import app
from atkits.github import GitHubReleaseClient
from atkits.lifecycle import StatusReport
from atkits.models import Catalog


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, fake_runtime) -> CliRunner:
    monkeypatch.setattr(cli_module, "_build_runtime", lambda: fake_runtime)
    return CliRunner()


def test_remote_list_groups_categories_without_downloading_packages(cli, fake_lifecycle):
    data = fake_lifecycle.catalog_data
    foo = data["skills"]["foo"]
    foo["description"] = "测试 [插件] 简介"
    version = foo["versions"]["1.1.0"]
    data["plugins"] = {"example-plugin": {"versions": {"1.1.0": version}}}
    data["cli"] = {"versions": {"1.1.0": version}}
    data["external_skills"].update(
        {
            "pdf": {"source": "openai/skills", "description": "处理 PDF"},
            "other": {"source": "example/skills"},
        }
    )
    result = cli.invoke(app, ["list", "--remote"], env={"NO_COLOR": "1", "COLUMNS": "100"})
    assert result.exit_code == 0
    output = Text.from_ansi(result.output).plain
    headings = ["自有技能（1）", "插件（1）", "外部技能收藏（2）", "CLI 工具（1）", "安装预设（1）"]
    starts = [output.index(f"\n{heading}") for heading in headings]
    assert starts == sorted(starts)
    skills, plugins, external, tools, presets = [
        output[start:end] for start, end in zip(starts, [*starts[1:], len(output)])
    ]
    assert "类型" not in output
    version_header = ["名称", "最新稳定版", "简介"]
    assert _table_rows(skills) == [version_header, ["foo", "1.1.0", "测试 [插件] 简介"]]
    assert _table_rows(plugins) == [version_header, ["example-plugin", "1.1.0", "—"]]
    assert _table_rows(external) == [
        ["名称", "来源仓库", "简介"],
        ["pdf", "openai/skills", "处理 PDF"],
        ["other", "example/skills", "—"],
    ]
    assert _table_rows(tools) == [version_header, ["atkits", "1.1.0", "—"]]
    assert "daily-coding" in presets
    assert fake_lifecycle.package_downloads == 0


def test_remote_list_wraps_source_and_description_in_narrow_terminal(cli, fake_lifecycle):
    source = "nextlevelbuilder/ui-ux-pro-max-skill"
    description = "规划产品界面的排版、间距、视觉层级和交互细节，提供完整设计建议"
    fake_lifecycle.catalog_data["external_skills"] = {
        "ui-ux-pro-max": {"source": source, "description": description}
    }
    result = cli.invoke(app, ["list", "--remote"], env={"NO_COLOR": "1", "COLUMNS": "64"})
    assert result.exit_code == 0
    output = Text.from_ansi(result.output).plain
    external = output.split("外部技能收藏（1）")[1].split("安装预设（1）")[0]
    rows = _table_rows(external)[1:]
    assert len(rows) > 1
    assert ["".join(row[i] for row in rows) for i in range(3)] == [
        "ui-ux-pro-max",
        source,
        description,
    ]


def test_remote_list_has_empty_state(cli, fake_lifecycle, monkeypatch):
    monkeypatch.setattr(fake_lifecycle, "check", lambda: Catalog({"schema_version": 1}))
    result = cli.invoke(app, ["list", "--remote"])
    assert result.exit_code == 0
    assert "暂无远端条目" in result.output
    assert "外部技能收藏" not in result.output


def _table_rows(output):
    return [
        [cell.strip() for cell in line.split("│")[1:-1]]
        for line in output.splitlines()
        if line.strip().startswith("│")
    ]


def test_list_groups_matching_installs_and_keeps_path_details(
    cli, fake_lifecycle, install_target, tmp_path, monkeypatch
):
    codex = replace(install_target, path=tmp_path / ".agents/skills/foo", consumers=("codex",))
    claude = replace(codex, path=tmp_path / ".claude/skills/foo", consumers=("claude",))
    project = replace(
        codex,
        scope="project",
        project_id="example",
        path=tmp_path / "project/.agents/skills/foo",
    )
    reports = [StatusReport(record, True) for record in (codex, claude, project)]
    monkeypatch.setattr(fake_lifecycle, "status", lambda: reports)
    env = {"COLUMNS": "240"}

    summary = cli.invoke(app, ["list"], env=env)
    assert summary.exit_code == 0, summary.exception
    assert _table_rows(summary.output) == [["skill", "foo", "1.1.0", "codex, claude", "ok"]]

    details = cli.invoke(app, ["list", "--details"], env=env)
    assert details.exit_code == 0, details.exception
    assert _table_rows(details.output) == [
        ["skill", "foo", "1.1.0", str(record.path), record.consumers[0], "ok"]
        for record in (codex, claude, project)
    ]


def test_list_keeps_distinct_versions_and_broken_targets_visible(
    cli, fake_lifecycle, install_target, monkeypatch
):
    reports = [
        StatusReport(replace(install_target, consumers=("codex", "cursor")), True),
        StatusReport(replace(install_target, consumers=("claude",)), False),
        StatusReport(replace(install_target, version="1.0.0", consumers=("claude",)), True),
        StatusReport(replace(install_target, kind="plugin", consumers=("codex",)), True),
    ]
    monkeypatch.setattr(fake_lifecycle, "status", lambda: reports)
    result = cli.invoke(app, ["list"], env={"COLUMNS": "120"})
    assert result.exit_code == 0, result.exception
    assert _table_rows(result.output) == [
        ["skill", "foo", "1.1.0", "codex, cursor", "ok"],
        ["skill", "foo", "1.1.0", "claude", "broken"],
        ["skill", "foo", "1.0.0", "claude", "ok"],
        ["plugin", "foo", "1.1.0", "codex", "ok"],
    ]


def test_list_details_cannot_be_used_for_remote_catalog(cli):
    result = cli.invoke(
        app,
        ["list", "--remote", "--details"],
        env={"COLUMNS": "120", "FORCE_COLOR": "1"},
        color=True,
    )
    assert result.exit_code == 2
    assert "不能与 --remote 同用" in Text.from_ansi(result.output).plain


def test_install_requires_explicit_platform_with_no_input(cli, fake_lifecycle):
    result = cli.invoke(app, ["install", "foo", "--no-input"])
    assert result.exit_code == 2
    assert "platform" in result.output


def test_install_without_terminal_does_not_prompt(cli, fake_lifecycle):
    result = cli.invoke(app, ["install", "foo"])
    assert result.exit_code == 2
    assert "非交互安装" in result.output
    assert "--platform" in result.output
    assert fake_lifecycle.package_downloads == 0


def test_install_interactively_passes_selected_platforms(cli, fake_lifecycle, monkeypatch):
    monkeypatch.setattr(cli_module, "_has_interactive_terminal", lambda: True)

    def choose(registry):
        assert registry["codex"].display_name == "Codex"
        assert registry["claude"].display_name == "Claude Code"
        return ["codex", "claude"]

    monkeypatch.setattr(cli_module, "_prompt_platforms", choose)
    result = cli.invoke(app, ["install", "foo"])
    assert result.exit_code == 0
    assert fake_lifecycle.last_request["platform_ids"] == ["codex", "claude"]
    assert fake_lifecycle.last_request["scope"] == "global"
    assert fake_lifecycle.last_request["method"] == "symlink"


def test_platform_menu_handles_arrow_keys_search_and_empty_selection():
    registry = cli_module.load_registry()
    choices = {key: registry[key] for key in ("codex", "claude")}
    with create_pipe_input() as terminal_input:
        # Submit empty, move down and back up, select Codex, then search and select Claude Code.
        terminal_input.send_bytes(b"\r\x1b[C\x1b[D\x1b[B\x1b[A claude \r\x03")
        with create_app_session(input=terminal_input, output=DummyOutput()):
            assert cli_module._prompt_platforms(choices) == ["codex", "claude"]


@pytest.mark.parametrize(("keys", "expected"), [(b"\r", "copy"), (b"\x1b[B\r", "symlink")])
def test_windows_method_menu_defaults_to_copy_but_allows_symlink(keys, expected):
    with create_pipe_input() as terminal_input:
        terminal_input.send_bytes(keys + b"\x03")
        with create_app_session(input=terminal_input, output=DummyOutput()):
            assert cli_module._prompt_install_method() == expected


@pytest.mark.parametrize(
    ("os_name", "tty", "options", "prompts", "method"),
    [
        ("windows", True, [], True, "copy"),
        ("windows", True, ["--no-input"], False, "symlink"),
        ("windows", False, [], False, "symlink"),
        ("windows", True, ["--method", "symlink"], False, "symlink"),
        ("windows", True, ["--method", "copy"], False, "copy"),
        ("windows", True, ["--preset", "daily-coding"], False, "symlink"),
        ("windows", True, ["--preset", "daily-coding", "--method", "copy"], False, "copy"),
        ("darwin", True, [], False, "symlink"),
        ("darwin", True, ["--method", "copy"], False, "copy"),
        ("darwin", True, ["--preset", "daily-coding", "--method", "copy"], False, "symlink"),
    ],
)
def test_install_prompts_for_method_only_on_interactive_windows(
    cli, fake_lifecycle, monkeypatch, os_name, tty, options, prompts, method
):
    calls = []

    def choose():
        calls.append(True)
        return "copy"

    monkeypatch.setattr(cli_module, "_current_os_name", lambda: os_name)
    monkeypatch.setattr(cli_module, "_has_interactive_terminal", lambda: tty)
    monkeypatch.setattr(cli_module, "_prompt_install_method", choose)
    result = cli.invoke(app, ["install", "foo", "--platform", "codex", *options])
    assert result.exit_code == 0, result.exception
    assert calls == ([True] if prompts else [])
    assert fake_lifecycle.last_request["method"] == method


def test_cancelling_windows_method_menu_does_not_install(cli, fake_lifecycle, monkeypatch):
    class FakeQuestion:
        def unsafe_ask(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(cli_module, "_current_os_name", lambda: "windows")
    monkeypatch.setattr(cli_module, "_has_interactive_terminal", lambda: True)
    monkeypatch.setattr(cli_module.questionary, "select", lambda *args, **kwargs: FakeQuestion())
    result = cli.invoke(app, ["install", "foo", "--platform", "codex"])
    assert result.exit_code == 130
    assert "已取消安装" in result.output
    assert fake_lifecycle.package_downloads == 0


def test_install_cancel_does_not_download_package(cli, fake_lifecycle, monkeypatch):
    monkeypatch.setattr(cli_module, "_has_interactive_terminal", lambda: True)

    class FakeQuestion:
        def unsafe_ask(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(cli_module.questionary, "checkbox", lambda *args, **kwargs: FakeQuestion())
    result = cli.invoke(app, ["install", "foo"])
    assert result.exit_code == 130
    assert "已取消安装" in result.output
    assert fake_lifecycle.package_downloads == 0


def test_install_reports_unknown_platform_without_installing(cli, fake_lifecycle):
    result = cli.invoke(app, ["install", "foo", "--platform", "codex,cluade", "--no-input"])
    assert result.exit_code == 2
    assert "未知平台" in result.output
    assert "'cluade'" in result.output
    assert "claude" in result.output.split("可用平台 ID：", 1)[1]
    assert "Traceback" not in result.output
    assert fake_lifecycle.package_downloads == 0


@pytest.mark.parametrize("command", ["install", "uninstall"])
def test_claude_legacy_alias_is_accepted_and_deduplicated(cli, fake_lifecycle, command):
    result = cli.invoke(app, [command, "foo", "--platform", "claude-code,claude"])
    assert result.exit_code == 0, result.exception
    assert fake_lifecycle.last_request["platform_ids"] == ["claude"]


def test_platforms_displays_only_canonical_claude_id(cli):
    result = cli.invoke(app, ["platforms"])
    assert result.exit_code == 0
    assert "claude" in result.output
    assert "claude-code" not in result.output


@pytest.mark.parametrize("command", [["install", "foo"], ["list"], ["self-update"]])
def test_uninitialized_cli_shows_registry_hint(monkeypatch, command):
    def uninitialized():
        raise cli_module.LifecycleError("请先运行 atkits init 配置 registry")

    monkeypatch.setattr(cli_module, "_build_runtime", uninitialized)
    result = CliRunner().invoke(app, command)
    assert result.exit_code == 1
    assert "请先运行 atkits init" in result.output
    assert "Traceback" not in result.output


def test_install_prints_every_physical_target(cli, fake_lifecycle):
    """选 codex,cursor,claude 会落到三个物理路径，输出必须全部列出。"""
    fake_lifecycle.install_targets = [
        SimpleNamespace(path=Path.home() / ".agents/skills/foo", consumers=("codex", "cursor")),
        SimpleNamespace(path=Path.home() / ".cursor/skills/foo", consumers=("cursor",)),
        SimpleNamespace(path=Path.home() / ".claude/skills/foo", consumers=("claude",)),
    ]
    result = cli.invoke(
        app,
        ["install", "foo", "--platform", "codex,cursor,claude", "--no-input"],
        env={"NO_COLOR": "1", "COLUMNS": "120"},
    )
    assert result.exit_code == 0
    output = Text.from_ansi(result.output).plain
    assert "~/.agents/skills/foo" in output
    assert "~/.cursor/skills/foo" in output
    assert "~/.claude/skills/foo" in output


def test_install_output_names_consumers_per_target(cli, fake_lifecycle):
    """共享路径要标出 consumers，用户才知道哪些平台共用这一份。"""
    fake_lifecycle.install_targets = [
        SimpleNamespace(path=Path.home() / ".agents/skills/foo", consumers=("codex", "cursor")),
        SimpleNamespace(path=Path.home() / ".claude/skills/foo", consumers=("claude",)),
    ]
    result = cli.invoke(
        app,
        ["install", "foo", "--platform", "codex,cursor,claude", "--no-input"],
        env={"NO_COLOR": "1", "COLUMNS": "120"},
    )
    assert result.exit_code == 0
    output = Text.from_ansi(result.output).plain
    agents_line = next(line for line in output.splitlines() if ".agents/skills/foo" in line)
    assert "codex" in agents_line and "cursor" in agents_line


def test_install_single_target_output_stays_one_line(cli, fake_lifecycle):
    fake_lifecycle.install_targets = [
        SimpleNamespace(path=Path.home() / ".agents/skills/foo", consumers=("codex",))
    ]
    result = cli.invoke(
        app,
        ["install", "foo", "--platform", "codex", "--no-input"],
        env={"NO_COLOR": "1", "COLUMNS": "120"},
    )
    assert result.exit_code == 0
    output = Text.from_ansi(result.output).plain
    assert "~/.agents/skills/foo" in output
    assert len([line for line in output.splitlines() if line.strip()]) == 1


def test_install_specific_version_and_platforms(cli, fake_lifecycle):
    result = cli.invoke(
        app,
        [
            "install",
            "foo@1.0.0",
            "--scope",
            "global",
            "--platform",
            "codex,cursor",
            "--method",
            "symlink",
        ],
    )
    assert result.exit_code == 0
    assert fake_lifecycle.last_request["platform_ids"] == ["codex", "cursor"]


def test_network_error_returns_exit_code_3(cli, fake_lifecycle):
    fake_lifecycle.fail_network = True
    result = cli.invoke(app, ["check"])
    assert result.exit_code == 3


def test_doctor_fix_repairs_package_and_symlink(cli, fake_lifecycle):
    fake_lifecycle.damage_managed_package()
    result = cli.invoke(app, ["doctor", "--fix"])
    assert result.exit_code == 0
    assert fake_lifecycle.repaired_target is not None


def test_old_apply_command_is_removed(cli):
    result = cli.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "apply" not in result.output


def test_install_editable_uses_source_path(cli, fake_lifecycle, tmp_path):
    source = tmp_path / "skills" / "foo"
    (source / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
    (source / "SKILL.md").write_text("---\nname: foo\n---\n", encoding="utf-8")
    result = cli.invoke(
        app,
        [
            "install",
            str(source),
            "--editable",
            "--scope",
            "global",
            "--platform",
            "codex",
        ],
    )
    assert result.exit_code == 0
    assert fake_lifecycle.last_request["source_path"] == source


def test_version(cli):
    result = cli.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "atkits" in result.output


def test_install_uses_catalog_preset(cli, fake_lifecycle):
    result = cli.invoke(
        app,
        ["install", "foo", "--preset", "daily-coding", "--no-input"],
    )
    assert result.exit_code == 0
    assert fake_lifecycle.last_request["platform_ids"] == ["codex", "cursor"]
    assert fake_lifecycle.last_request["method"] == "symlink"
    assert fake_lifecycle.last_request["scope"] == "global"


def test_self_update_command_downloads_wheel(home, http_server, monkeypatch: pytest.MonkeyPatch):
    wheel_name = "atkits-0.2.0-py3-none-any.whl"
    wheel_bytes = b"test wheel"
    home.save_config({"registry_repo": "owner/repo"})
    monkeypatch.setenv("ATKITS_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        cli_module,
        "GitHubReleaseClient",
        lambda repo, *, token: GitHubReleaseClient(repo, token=token, base_url=http_server.url),
    )
    catalog = {
        "schema_version": 1,
        "cli": {
            "latest": "0.2.0",
            "versions": {
                "0.2.0": {
                    "asset_id": 53,
                    "archive": wheel_name,
                    "sha256": hashlib.sha256(wheel_bytes).hexdigest(),
                }
            },
        },
    }
    http_server.set_route("/repos/owner/repo/releases/assets/52", 200, json.dumps(catalog).encode())
    http_server.set_route("/repos/owner/repo/releases/assets/53", 200, wheel_bytes)
    uv_calls = []

    def fake_uv(command, *, check, capture_output, text):
        uv_calls.append(command[:4])
        wheel = Path(command[4])
        assert wheel.name == wheel_name
        assert wheel.read_bytes() == wheel_bytes
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(self_update_module, "shutil", SimpleNamespace(which=lambda _name: "uv"))
    monkeypatch.setattr(self_update_module, "subprocess", SimpleNamespace(run=fake_uv))
    result = CliRunner().invoke(app, ["self-update"])

    assert result.exit_code == 0, result.exception
    assert uv_calls == [["uv", "tool", "install", "--force"]]
    assert [request.path for request in http_server.requests] == [
        "/repos/owner/repo/releases/tags/registry",
        "/repos/owner/repo/releases/assets/52",
        "/repos/owner/repo/releases/assets/53",
    ]
    assert http_server.requests[-1].headers["Authorization"] == "Bearer test-token"
    assert "0.2.0" in result.output


@pytest.mark.parametrize("mode", ["valid", "corrupt", "winerror_1314"])
def test_install_remote_checks_package_before_registering(
    home, http_server, catalog_data, asset, valid_archive, tmp_path, monkeypatch, mode
):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("ATKITS_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        cli_module,
        "GitHubReleaseClient",
        lambda repo, *, token: GitHubReleaseClient(repo, token=token, base_url=http_server.url),
    )
    home.save_config({"registry_repo": "owner/repo"})
    catalog_data["skills"]["foo"]["versions"]["1.1.0"]["sha256"] = asset.sha256
    catalog_path = "/repos/owner/repo/releases/assets/52"
    package_path = f"/repos/owner/repo/releases/assets/{asset.asset_id}"
    http_server.set_route(catalog_path, 200, json.dumps(catalog_data).encode())
    http_server.set_route(
        package_path, 200, b"corrupt" if mode == "corrupt" else valid_archive.read_bytes()
    )
    if mode == "winerror_1314":

        def reject_symlink(*args, **kwargs):
            error = OSError("A required privilege is not held by the client")
            error.winerror = 1314
            raise error

        monkeypatch.setattr(cli_module, "_current_os_name", lambda: "windows")
        monkeypatch.setattr("atkits.installers.os", SimpleNamespace(symlink=reject_symlink))

    runner = CliRunner()
    args = ["install", "foo", "--platform", "codex", "--no-input"]
    result = runner.invoke(app, args)
    target = fake_home / ".agents" / "skills" / "foo"
    assert any(request.path == package_path for request in http_server.requests), result.exception
    if mode == "corrupt":
        assert result.exit_code == 1
        assert "sha256 mismatch" in result.output
        assert not target.exists()
        assert not home.state_path.exists()
    elif mode == "winerror_1314":
        output = " ".join(Text.from_ansi(result.output).plain.split())
        assert result.exit_code == 1
        assert "WinError 1314" in output and "--method copy" in output
        assert "Traceback" not in output
        assert not target.exists()
        assert not home.state_path.exists()

        retry = runner.invoke(app, [*args, "--method", "copy"])
        assert retry.exit_code == 0, retry.exception
        assert not target.is_symlink()
        assert (target / "SKILL.md").is_file()
        (record,) = json.loads(home.state_path.read_text())["installs"].values()
        assert record["strategy"] == "copy"
    else:
        assert result.exit_code == 0, result.exception
        assert target.is_symlink()
        assert target.resolve() == (home.packages_path / "skills" / "foo" / "1.1.0").resolve()
        listing = runner.invoke(app, ["list"])
        assert listing.exit_code == 0
        assert "foo" in listing.output
        assert "1.1.0" in listing.output
    assert not list(home.tmp_path.glob("download-*"))


def test_install_external_skill(cli, fake_runtime, monkeypatch: pytest.MonkeyPatch):
    from atkits.external import ExternalHealth

    class FakeExternalInstaller:
        def __init__(self, catalog, home, *, os_name, env, command_runner=None):
            self.catalog = catalog
            self.home = home
            self.os_name = os_name
            self.env = env

        def install(self, name: str, platform_ids: list[str]):
            return ExternalHealth(installed=True, path=Path(f"/tmp/{name}"))

    monkeypatch.setattr(cli_module, "ExternalInstaller", FakeExternalInstaller)
    result = cli.invoke(
        app,
        ["install", "pdf", "--platform", "codex", "--no-input"],
    )
    assert result.exit_code == 0
    assert "pdf" in result.output


def test_documented_commands_exist_in_help_and_readme(cli):
    commands = [
        "init",
        "list",
        "check",
        "status",
        "install",
        "uninstall",
        "update",
        "doctor",
        "cache",
        "self-update",
        "platforms",
    ]
    result = cli.invoke(app, ["--help"])
    assert result.exit_code == 0
    readme = Path("README.md").read_text(encoding="utf-8")
    for command in commands:
        assert command in result.output
        assert command in readme
    cache_result = cli.invoke(app, ["cache", "--help"])
    assert cache_result.exit_code == 0
    assert "prune" in cache_result.output
