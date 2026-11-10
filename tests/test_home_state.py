from pathlib import Path

import dataclasses

import pytest

from atkits.home import AtkitsHome
from atkits.state import StateStore


def test_state_round_trip_and_atomic_replace(home, install_target):
    store = StateStore(home)
    store.put(install_target)
    assert (
        store.get_target(
            "skill",
            "foo",
            "global",
            install_target.project_id,
            install_target.target_id,
        )
        == install_target
    )
    assert not list(home.path.glob("state.json.tmp*"))


def test_remove_consumer_keeps_shared_target(home, install_target):
    store = StateStore(home)
    store.put(dataclasses.replace(install_target, consumers=("codex", "cursor")))
    store.remove_consumer(
        "skill",
        "foo",
        "global",
        install_target.project_id,
        install_target.target_id,
        "codex",
    )
    record = store.get_target(
        "skill", "foo", "global", install_target.project_id, install_target.target_id
    )
    assert record.consumers == ("cursor",)


def test_project_state_keys_do_not_collide(
    home, project_install_target, other_project_install_target
):
    store = StateStore(home)
    store.put(project_install_target)
    store.put(other_project_install_target)
    assert (
        store.get_target("skill", "foo", "project", project_install_target.project_id, "agents")
        == project_install_target
    )
    assert (
        store.get_target(
            "skill", "foo", "project", other_project_install_target.project_id, "agents"
        )
        == other_project_install_target
    )


def test_home_never_writes_outside_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ATKITS_HOME", str(tmp_path / "custom"))
    home = AtkitsHome.discover()
    home.ensure_layout()
    assert (tmp_path / "custom/packages").is_dir()
    assert home.path == tmp_path / "custom"


def test_config_round_trip_and_token_rejection(home):
    home.save_config(
        {
            "registry_repo": "Mikko-ww/agent-tool-kits",
            "catalog_ttl_seconds": 300,
            "preferred_platforms": ["codex", "cursor"],
        }
    )
    assert home.load_config() == {
        "registry_repo": "Mikko-ww/agent-tool-kits",
        "catalog_ttl_seconds": 300,
        "preferred_platforms": ["codex", "cursor"],
    }
    with pytest.raises(ValueError, match="token"):
        home.save_config({"GITHUB_TOKEN": "secret"})


def test_state_remove_and_all(home, install_target):
    store = StateStore(home)
    store.put(install_target)
    assert store.all() == [install_target]
    store.remove(
        "skill",
        "foo",
        "global",
        install_target.project_id,
        install_target.target_id,
    )
    assert store.all() == []


def test_state_store_creates_lock_directory(tmp_path: Path) -> None:
    home = AtkitsHome(tmp_path / "atkits")
    StateStore(home)
    assert home.locks_path.is_dir()
