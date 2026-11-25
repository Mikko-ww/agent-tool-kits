import hashlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import atkits.self_update as self_update_module
from atkits.models import AssetVersion, Catalog
from atkits.self_update import SelfUpdateError, latest_cli_wheel, self_update

# uv 在中文 Windows 上仍输出 UTF-8，这些字节用 GBK 解码会失败。
UTF8_MESSAGE = "error: 拒绝访问 C:\\Users\\ELEX"


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


def test_self_update_decodes_uv_output_as_utf8(
    fake_runtime, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """子进程输出必须按 UTF-8 解码，不能用系统本地编码（中文 Windows 是 GBK）。"""
    real_run = subprocess.run
    script = tmp_path / "fake_uv.py"
    script.write_text(
        f"import sys\nsys.stderr.buffer.write({UTF8_MESSAGE.encode('utf-8')!r})\nsys.exit(1)\n",
        encoding="utf-8",
    )
    seen: list[dict[str, object]] = []

    def locale_decoding_run(cmd, **kwargs):
        seen.append(kwargs)
        # 模拟中文 Windows：真实子进程输出 UTF-8，父进程按 GBK 解码。
        # 生产代码显式要求 utf-8 时才如实照办，否则退回本地编码。
        encoding = "utf-8" if kwargs.get("encoding") == "utf-8" else "gbk"
        return real_run(
            [sys.executable, str(script)],
            capture_output=True,
            encoding=encoding,
            errors=kwargs.get("errors", "strict"),
        )

    monkeypatch.setattr(self_update_module.shutil, "which", lambda _name: sys.executable)
    monkeypatch.setattr(self_update_module.subprocess, "run", locale_decoding_run)

    with pytest.raises(SelfUpdateError) as excinfo:
        self_update(
            uv_executable="uv",
            registry=fake_runtime.catalog,
            downloader=fake_runtime.download,
        )

    assert seen, "self_update 没有调用 subprocess.run"
    assert seen[0].get("encoding") == "utf-8"
    assert seen[0].get("errors") == "replace"
    assert UTF8_MESSAGE in str(excinfo.value)


def test_self_update_reports_failure_when_output_is_missing(
    fake_runtime, monkeypatch: pytest.MonkeyPatch
):
    """读取线程解码失败会让 stdout/stderr 变成 None，此时仍要给出可读错误。"""
    monkeypatch.setattr(self_update_module.shutil, "which", lambda _name: "uv")
    monkeypatch.setattr(
        self_update_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=None, stderr=None),
    )

    with pytest.raises(SelfUpdateError, match="退出码 1"):
        self_update(
            uv_executable="uv",
            registry=fake_runtime.catalog,
            downloader=fake_runtime.download,
        )
