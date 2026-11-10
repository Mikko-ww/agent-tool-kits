from pathlib import Path

import pytest

from atkits.external import ExternalError, ExternalInstaller, _default_command_runner


@pytest.fixture
def external_installer(platform_env, catalog_data):
    def runner(source: str, name: str, platform_ids: list[str]) -> None:
        target = platform_env.home / ".agents/skills" / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: external\n---\n",
            encoding="utf-8",
        )

    return ExternalInstaller(
        catalog_data,
        platform_env.home,
        os_name="darwin",
        env=platform_env.env,
        command_runner=runner,
    )


def test_broken_external_symlink_is_not_installed(external_installer, tmp_path: Path):
    target = tmp_path / "missing"
    target.symlink_to(tmp_path / "does-not-exist")
    health = external_installer.health("missing", paths=[target])
    assert health.installed is False


def test_external_install_requires_resolved_skill_dir(external_installer):
    result = external_installer.install("pdf", platform_ids=["codex"])
    assert result.installed is True
    assert (result.path / "SKILL.md").is_file()


def test_external_install_rejects_missing_skill_after_runner(external_installer, monkeypatch):
    monkeypatch.setattr(
        external_installer,
        "command_runner",
        lambda source, name, platform_ids: None,
    )
    with pytest.raises(ExternalError, match="not installed"):
        external_installer.install("pdf", platform_ids=["codex"])


def test_external_health_rejects_regular_file(external_installer, tmp_path: Path):
    path = tmp_path / "pdf"
    path.write_text("not a directory")
    health = external_installer.health("pdf", paths=[path])
    assert health.installed is False


def test_default_command_runner_calls_run_add(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def fake_run_add(source, skill_names, agents, *, global_scope, cwd, dry_run):
        calls.append((source, skill_names, agents, global_scope, cwd, dry_run))

    monkeypatch.setattr("atkits.external.run_add", fake_run_add)
    _default_command_runner("openai/skills", "pdf", ["codex"])
    assert calls == [("openai/skills", ["pdf"], ["codex"], True, None, False)]
