from pathlib import Path

import pytest

from atkits.platforms import (
    PlatformError,
    detect_platforms,
    load_registry,
    project_id,
    resolve_targets,
    same_physical_path,
)


def test_project_codex_cursor_opencode_share_agents_dir(platform_env):
    targets = resolve_targets(
        "project",
        ["codex", "cursor", "opencode"],
        platform_env.cwd,
        os_name="darwin",
        env=platform_env.env,
    )
    agents = [target for target in targets if target.target_id == "agents"]
    assert len(agents) == 1
    assert agents[0].path == platform_env.cwd / ".agents/skills"
    assert set(agents[0].consumers) == {"codex", "cursor", "opencode"}
    assert agents[0].shared is True


def test_cursor_global_has_primary_and_shared_paths(platform_env):
    targets = resolve_targets(
        "global", ["cursor"], platform_env.cwd, os_name="darwin", env=platform_env.env
    )
    paths = {target.target_id: target.path for target in targets}
    assert paths["cursor"] == platform_env.home / ".cursor/skills"
    assert paths["agents"] == platform_env.home / ".agents/skills"


def test_opencode_uses_xdg_primary_and_agents_compatibility(platform_env):
    targets = resolve_targets(
        "global", ["opencode"], platform_env.cwd, os_name="linux", env=platform_env.env
    )
    paths = {target.target_id: target.path for target in targets}
    assert paths["opencode"] == platform_env.xdg_config / "opencode/skills"
    assert paths["agents"] == platform_env.home / ".agents/skills"
    roles = {target.target_id: target.role for target in targets}
    assert roles["opencode"] == "primary"
    assert roles["agents"] == "compatibility"


def test_windows_path_spec_is_filtered_by_os(platform_env):
    targets = resolve_targets(
        "global",
        ["example-windows-only"],
        platform_env.cwd,
        os_name="darwin",
        env=platform_env.env,
    )
    assert targets == ()


def test_windows_path_comparison_uses_normcase():
    assert same_physical_path(Path("C:/Users/Foo/Skills"), Path("c:\\users\\foo\\skills"))


def test_project_id_is_stable_for_equivalent_paths(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    assert project_id(root) == project_id(root / ".")
    assert project_id(root) != project_id(tmp_path / "other")


def test_load_registry_reads_packaged_file():
    registry = load_registry()
    assert {"codex", "cursor", "opencode"}.issubset(registry)


def test_detect_platforms_uses_existing_paths(platform_env):
    (platform_env.home / ".cursor").mkdir()
    detected = detect_platforms("darwin", platform_env.env, platform_env.home)
    assert "cursor" in detected


def test_unknown_platform_raises(platform_env):
    with pytest.raises(PlatformError):
        resolve_targets(
            "global", ["does-not-exist"], platform_env.cwd, os_name="darwin", env=platform_env.env
        )
