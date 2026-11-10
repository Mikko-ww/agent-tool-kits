import pytest

from atkits.lifecycle import InstallConflict, LifecycleError


def test_install_update_and_offline_rollback(lifecycle):
    installed = lifecycle.install(
        "skill", "foo", "1.0.0", platform_ids=["codex"], scope="global", method="symlink"
    )
    assert installed.version == "1.0.0"
    updated = lifecycle.update("skill", "foo", scope="global")
    assert updated.version == "1.1.0"
    lifecycle.fake_registry.set_offline(True)
    rolled_back = lifecycle.install(
        "skill", "foo", "1.0.0", platform_ids=["codex"], scope="global", method="symlink"
    )
    assert rolled_back.version == "1.0.0"


def test_shared_target_rejects_version_mismatch(lifecycle, project_root):
    lifecycle.install(
        "skill",
        "foo",
        "1.0.0",
        platform_ids=["codex"],
        scope="project",
        project_root=project_root,
        method="symlink",
    )
    with pytest.raises(InstallConflict, match="shared target"):
        lifecycle.install(
            "skill",
            "foo",
            "1.1.0",
            platform_ids=["cursor"],
            scope="project",
            project_root=project_root,
            method="symlink",
        )


def test_project_targets_are_isolated_by_project_id(lifecycle, project_root, other_project_root):
    first = lifecycle.install(
        "skill",
        "foo",
        "1.0.0",
        platform_ids=["codex"],
        scope="project",
        project_root=project_root,
        method="symlink",
    )
    second = lifecycle.install(
        "skill",
        "foo",
        "1.1.0",
        platform_ids=["codex"],
        scope="project",
        project_root=other_project_root,
        method="symlink",
    )
    assert first.path != second.path
    assert first.project_id != second.project_id
    assert first.version == "1.0.0"
    assert second.version == "1.1.0"


def test_update_shared_target_reports_all_affected_consumers(lifecycle):
    lifecycle.install(
        "skill",
        "foo",
        "1.0.0",
        platform_ids=["codex", "cursor"],
        scope="global",
        method="symlink",
    )
    plan = lifecycle.plan_update("skill", "foo", scope="global")
    assert set(plan.affected_consumers) == {"codex", "cursor"}
    assert plan.path.name == "foo"


def test_uninstall_removed_remote_asset_still_uses_local_state(lifecycle):
    lifecycle.install("plugin", "bar", platform_ids=["cursor"], scope="global", method="copy")
    lifecycle.fake_registry.remove("plugin", "bar")
    lifecycle.uninstall("plugin", "bar", scope="global", platform_ids=["cursor"])
    assert lifecycle.state.all() == []


def test_status_reports_unhealthy_target(lifecycle):
    installed = lifecycle.install(
        "skill", "foo", platform_ids=["codex"], scope="global", method="symlink"
    )
    reports = lifecycle.status()
    assert reports[0].record == installed.targets[0]
    assert reports[0].healthy is True
    installed.targets[0].path.unlink()
    reports = lifecycle.status()
    assert reports[0].healthy is False


def test_prune_cache_removes_unreferenced_package(lifecycle, home):
    unreferenced = home.packages_path / "skills" / "foo" / "0.9.0"
    unreferenced.mkdir(parents=True)
    (unreferenced / "SKILL.md").write_text("old", encoding="utf-8")

    removed = lifecycle.prune_cache()

    assert unreferenced in removed
    assert not unreferenced.exists()


def test_uninstall_project_requires_project_root(lifecycle):
    with pytest.raises(LifecycleError):
        lifecycle.uninstall("skill", "foo", scope="project", platform_ids=["codex"])
