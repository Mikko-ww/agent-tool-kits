import pytest
from typer.testing import CliRunner

import atkits.cli as cli_module
from atkits.cli import app


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
