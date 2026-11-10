from pathlib import Path

import pytest

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
