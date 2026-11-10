import tarfile
from pathlib import Path

import pytest

from scripts.package_asset import PackageAssetError, package_asset
from scripts.update_catalog import build_catalog


@pytest.fixture
def repo_with_two_skills(tmp_path: Path) -> Path:
    for name, version in [("foo", "1.1.0"), ("bar", "0.1.0")]:
        skill = tmp_path / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test\nmetadata:\n  version: {version}\n---\n",
            encoding="utf-8",
        )
        (skill / "reference.md").write_text("reference\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def releases() -> list[dict[str, object]]:
    return [
        {
            "tag_name": "skill-foo-v1.0.0",
            "assets": [{"id": 1, "name": "foo-1.0.0.tar.gz", "sha256": "0" * 64}],
        },
        {
            "tag_name": "skill-foo-v1.2.0",
            "assets": [{"id": 2, "name": "foo-1.2.0.tar.gz", "sha256": "1" * 64}],
        },
        {
            "tag_name": "skill-foo-v1.1.0",
            "assets": [{"id": 3, "name": "foo-1.1.0.tar.gz", "sha256": "2" * 64}],
        },
        {
            "tag_name": "plugin-bar-v0.1.0",
            "assets": [{"id": 4, "name": "bar-0.1.0.tar.gz", "sha256": "3" * 64}],
        },
    ]


@pytest.fixture
def favorites() -> dict[str, object]:
    return {
        "external_skills": {
            "pdf": {"source": "openai/skills"},
        },
        "presets": {
            "daily-coding": {
                "scope": "global",
                "platforms": ["codex", "cursor"],
                "method": "symlink",
            },
        },
    }


def test_package_contains_only_selected_skill(repo_with_two_skills, tmp_path: Path):
    archive = package_asset("skill", "foo", "1.1.0", repo_with_two_skills, tmp_path)
    with tarfile.open(archive) as tf:
        names = tf.getnames()
    assert "foo/SKILL.md" in names
    assert "foo/reference.md" in names
    assert not any(name.startswith("bar/") for name in names)
    assert archive.name == "foo-1.1.0.tar.gz"
    assert (tmp_path / "foo-1.1.0.tar.gz.sha256").is_file()


def test_package_rejects_version_mismatch(repo_with_two_skills, tmp_path: Path):
    with pytest.raises(PackageAssetError, match="version"):
        package_asset("skill", "foo", "9.9.9", repo_with_two_skills, tmp_path)


def test_catalog_latest_uses_semver_precedence(releases, favorites):
    catalog = build_catalog(releases, favorites)
    assert catalog["schema_version"] == 1
    assert catalog["skills"]["foo"]["latest"] == "1.2.0"
    assert set(catalog["skills"]["foo"]["versions"]) == {
        "1.0.0",
        "1.1.0",
        "1.2.0",
    }
    assert catalog["plugins"]["bar"]["latest"] == "0.1.0"
    assert catalog["external_skills"]["pdf"]["source"] == "openai/skills"
    assert catalog["collection"]["presets"]["daily-coding"]["scope"] == "global"


def test_package_plugin_contains_manifest_and_skills(tmp_path: Path):
    repo = tmp_path / "repo"
    plugin = repo / "plugins" / "bar"
    (plugin / "skills").mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("name: bar\nversion: 0.1.0\n", encoding="utf-8")
    (plugin / "skills/README.md").write_text("plugin\n", encoding="utf-8")
    archive = package_asset("plugin", "bar", "0.1.0", repo, tmp_path / "dist")
    with tarfile.open(archive) as tf:
        names = tf.getnames()
    assert "bar/plugin.yaml" in names
    assert "bar/skills/README.md" in names


def test_build_catalog_handles_cli_release():
    releases = [
        {
            "tag_name": "cli-v0.2.0",
            "assets": [{"id": 9, "name": "atkits-0.2.0-py3-none-any.whl", "sha256": "4" * 64}],
        }
    ]
    catalog = build_catalog(releases, {})
    assert catalog["cli"]["latest"] == "0.2.0"
    assert "0.2.0" in catalog["cli"]["versions"]


def test_build_catalog_accepts_github_digest_field():
    releases = [
        {
            "tag_name": "skill-foo-v1.0.0",
            "assets": [{"id": 1, "name": "foo.tar.gz", "digest": f"sha256:{'0' * 64}"}],
        }
    ]
    catalog = build_catalog(releases, {})
    assert catalog["skills"]["foo"]["versions"]["1.0.0"]["sha256"] == "0" * 64


def test_generated_catalog_is_parseable(releases, favorites):
    from atkits.models import Catalog

    catalog = build_catalog(releases, favorites)
    parsed = Catalog(catalog)
    assert parsed.latest("skill", "foo").version == "1.2.0"
    assert parsed.preset("daily-coding").platforms == ("codex", "cursor")
