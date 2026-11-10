import dataclasses
from pathlib import Path

import pytest

from atkits.home import AtkitsHome
from atkits.models import Catalog, InstallTarget


@pytest.fixture
def catalog() -> Catalog:
    return Catalog(
        {
            "schema_version": 1,
            "skills": {
                "foo": {
                    "latest": "1.1.0",
                    "versions": {
                        "1.0.0": {
                            "asset_id": 10001,
                            "archive": "foo-1.0.0.tar.gz",
                            "sha256": "0" * 64,
                        },
                        "1.1.0": {
                            "asset_id": 10002,
                            "archive": "foo-1.1.0.tar.gz",
                            "sha256": "1" * 64,
                        },
                        "1.2.0-beta.1": {
                            "asset_id": 10003,
                            "archive": "foo-1.2.0-beta.1.tar.gz",
                            "sha256": "2" * 64,
                        },
                    },
                }
            },
        }
    )


@pytest.fixture
def install_target() -> InstallTarget:
    return InstallTarget(
        kind="skill",
        name="foo",
        scope="global",
        project_id=None,
        version="1.1.0",
        target_id="agents",
        path=Path("/home/user/.agents/skills/foo"),
        strategy="symlink",
        consumers=("codex",),
        package_path=Path("packages/skills/foo/1.1.0"),
        artifact_sha256="1" * 64,
        content_sha256="2" * 64,
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AtkitsHome:
    root = tmp_path / "atkits"
    monkeypatch.setenv("ATKITS_HOME", str(root))
    result = AtkitsHome.discover()
    result.ensure_layout()
    return result


@pytest.fixture
def project_install_target(install_target: InstallTarget) -> InstallTarget:
    return dataclasses.replace(
        install_target,
        scope="project",
        project_id="a" * 64,
        path=Path("/tmp/project-a/.agents/skills/foo"),
    )


@pytest.fixture
def other_project_install_target(install_target: InstallTarget) -> InstallTarget:
    return dataclasses.replace(
        install_target,
        scope="project",
        project_id="b" * 64,
        path=Path("/tmp/project-b/.agents/skills/foo"),
    )
