import hashlib
from pathlib import Path

import pytest

from atkits.models import AssetVersion, Catalog
from atkits.self_update import SelfUpdateError, latest_cli_wheel, self_update


@pytest.fixture
def cli_catalog() -> Catalog:
    wheel_hash = hashlib.sha256(b"fake wheel").hexdigest()
    return Catalog(
        {
            "schema_version": 1,
            "cli": {
                "latest": "0.2.0",
                "versions": {
                    "0.2.0": {
                        "asset_id": 42,
                        "archive": "atkits-0.2.0-py3-none-any.whl",
                        "sha256": wheel_hash,
                    }
                },
            },
        }
    )


@pytest.fixture
def fake_runtime(tmp_path: Path, cli_catalog: Catalog):
    state = {"installed_wheel": None, "expected_hash": cli_catalog.latest("cli", "atkits").sha256}

    def download(asset: AssetVersion, destination: Path) -> None:
        destination.write_bytes(b"fake wheel")
        state["downloaded_asset"] = asset

    def uv(command: list[str]) -> None:
        wheel = Path(command[-1])
        state["installed_wheel"] = wheel

    class Runtime:
        pass

    runtime = Runtime()
    runtime.catalog = cli_catalog
    runtime.download = download
    runtime.uv = uv
    runtime.state = state
    return runtime


def test_latest_cli_wheel(cli_catalog: Catalog):
    asset = latest_cli_wheel(cli_catalog)
    assert asset.version == "0.2.0"
    assert asset.archive == "atkits-0.2.0-py3-none-any.whl"


def test_self_update_downloads_verified_wheel_and_invokes_uv(fake_runtime):
    updated = self_update(
        uv_executable=fake_runtime.uv,
        registry=fake_runtime.catalog,
        downloader=fake_runtime.download,
    )
    assert updated.public == "0.2.0"
    assert fake_runtime.state["installed_wheel"].name == "atkits-0.2.0-py3-none-any.whl"
    assert fake_runtime.state["downloaded_asset"].sha256 == fake_runtime.state["expected_hash"]


def test_self_update_rejects_hash_mismatch(fake_runtime, monkeypatch: pytest.MonkeyPatch):
    def corrupt_downloader(asset: AssetVersion, destination: Path) -> None:
        destination.write_bytes(b"corrupted")

    with pytest.raises(SelfUpdateError, match="sha256"):
        self_update(
            uv_executable=fake_runtime.uv,
            registry=fake_runtime.catalog,
            downloader=corrupt_downloader,
        )
