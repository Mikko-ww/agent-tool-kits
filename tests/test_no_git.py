import shutil
from pathlib import Path

from typer.testing import CliRunner

import atkits.cli as cli_module
from atkits.cli import app


def test_core_workflow_runs_without_git_in_path(fake_runtime, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cli_module, "_build_runtime", lambda: fake_runtime)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    assert shutil.which("git") is None

    runner = CliRunner()
    result = runner.invoke(app, ["list", "--remote"])
    assert result.exit_code == 0

    result = runner.invoke(
        app,
        [
            "install",
            "foo@1.0.0",
            "--scope",
            "global",
            "--platform",
            "codex",
            "--method",
            "symlink",
        ],
    )
    assert result.exit_code == 0
