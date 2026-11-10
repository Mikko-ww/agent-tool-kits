from pathlib import Path

import pytest

from atkits.installers import InstallConflict


def test_copy_update_detects_user_modification(installer, plugin_record, package_v2):
    (plugin_record.target_path / "user.txt").write_text("local edit")
    with pytest.raises(InstallConflict, match="local modification"):
        installer.install(plugin_record, package_v2)


def test_uninstall_subset_keeps_shared_symlink(installer, shared_skill_record):
    installer.uninstall(shared_skill_record, consumers={"codex"})
    assert shared_skill_record.target_path.is_symlink()


def test_uninstall_all_consumers_removes_shared_symlink(installer, shared_skill_record):
    installer.uninstall(shared_skill_record, consumers={"codex", "cursor"})
    assert not shared_skill_record.target_path.exists()


def test_uninstall_does_not_touch_symlink_replacement(installer, skill_record, tmp_path: Path):
    skill_record.target_path.unlink()
    skill_record.target_path.symlink_to(tmp_path / "other")
    with pytest.raises(InstallConflict):
        installer.uninstall(skill_record, consumers={"codex"})
    assert skill_record.target_path.is_symlink()


def test_editable_install_uses_source_path_not_package_cache(
    installer, editable_record, source_repo
):
    installer.install(editable_record, package_dir=None)
    assert editable_record.target_path.readlink() == source_repo.skill_path
    assert editable_record.package_path is None


def test_symlink_install_replaces_expected_link(installer, skill_record, package_dir):
    installer.install(skill_record, package_dir)
    assert skill_record.target_path.readlink() == package_dir.resolve()


def test_copy_install_backs_up_matching_target(installer, plugin_record, package_v2):
    installer.install(plugin_record, package_v2)
    assert plugin_record.target_path.is_dir()
    assert (plugin_record.target_path / "plugin.yaml").is_file()
    assert any(
        backup.name.startswith("backup-") for backup in installer.backup_store.root.iterdir()
    )


def test_health_reports_expected_states(
    installer, skill_record, package_dir, plugin_record, package_v2
):
    installer.install(skill_record, package_dir)
    assert installer.health(skill_record) is True
    skill_record.target_path.unlink()
    assert installer.health(skill_record) is False

    installer.install(plugin_record, package_v2)
    assert installer.health(plugin_record) is True
    (plugin_record.target_path / "changed.txt").write_text("changed")
    assert installer.health(plugin_record) is False
