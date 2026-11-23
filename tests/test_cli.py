import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from typer.testing import CliRunner

import atkits.cli as cli_module
import atkits.self_update as self_update_module
from atkits.cli import app
from atkits.github import GitHubReleaseClient


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, fake_runtime) -> CliRunner:
    monkeypatch.setattr(cli_module, "_build_runtime", lambda: fake_runtime)
    return CliRunner()


def test_remote_list_does_not_download_packages(cli, fake_lifecycle):
    result = cli.invoke(app, ["list", "--remote"])
    assert result.exit_code == 0
    assert "foo" in result.output
    assert "pdf" in result.output
    assert "daily-coding" in result.output
    assert fake_lifecycle.package_downloads == 0


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
        assert registry["claude-code"].display_name == "Claude Code"
        return ["codex", "claude-code"]

    monkeypatch.setattr(cli_module, "_prompt_platforms", choose)
    result = cli.invoke(app, ["install", "foo"])
    assert result.exit_code == 0
    assert fake_lifecycle.last_request["platform_ids"] == ["codex", "claude-code"]
    assert fake_lifecycle.last_request["scope"] == "global"
    assert fake_lifecycle.last_request["method"] == "symlink"


def test_platform_menu_handles_arrow_keys_search_and_empty_selection():
    registry = cli_module.load_registry()
    choices = {key: registry[key] for key in ("codex", "claude-code")}
    with create_pipe_input() as terminal_input:
        # Submit empty, move down and back up, select Codex, then search and select Claude Code.
        terminal_input.send_bytes(b"\r\x1b[C\x1b[D\x1b[B\x1b[A claude \r\x03")
        with create_app_session(input=terminal_input, output=DummyOutput()):
            assert cli_module._prompt_platforms(choices) == ["codex", "claude-code"]


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
    result = cli.invoke(app, ["install", "foo", "--platform", "codex,claude", "--no-input"])
    assert result.exit_code == 2
    assert "未知平台" in result.output
    assert "'claude'" in result.output
    assert "claude-code" in result.output
    assert "Traceback" not in result.output
    assert fake_lifecycle.package_downloads == 0


@pytest.mark.parametrize("command", [["install", "foo"], ["list"], ["self-update"]])
def test_uninitialized_cli_shows_registry_hint(monkeypatch, command):
    def uninitialized():
        raise cli_module.LifecycleError("请先运行 atkits init 配置 registry")

    monkeypatch.setattr(cli_module, "_build_runtime", uninitialized)
    result = CliRunner().invoke(app, command)
    assert result.exit_code == 1
    assert "请先运行 atkits init" in result.output
    assert "Traceback" not in result.output


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
