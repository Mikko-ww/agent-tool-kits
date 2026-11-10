"""Self-update atkits from a private GitHub Release wheel."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from packaging.version import Version

from atkits.models import AssetVersion, Catalog
from atkits.packages import sha256_file


class SelfUpdateError(RuntimeError):
    """Raised when atkits cannot safely update itself."""


def latest_cli_wheel(registry: Catalog) -> AssetVersion:
    try:
        return registry.latest("cli", "atkits")
    except Exception as exc:
        raise SelfUpdateError("catalog does not contain a CLI wheel") from exc


def self_update(
    uv_executable: str | Callable[[list[str]], None] = "uv",
    *,
    registry: Catalog | None = None,
    downloader: Callable[[AssetVersion, Path], None] | None = None,
) -> Version:
    if registry is None:
        raise SelfUpdateError("self-update requires a catalog")
    if downloader is None:
        raise SelfUpdateError("self-update requires a downloader")

    asset = latest_cli_wheel(registry)
    with tempfile.TemporaryDirectory(prefix="atkits-self-update-") as temporary:
        destination = Path(temporary) / asset.archive
        downloader(asset, destination)
        actual_hash = sha256_file(destination)
        if actual_hash != asset.sha256:
            raise SelfUpdateError(
                f"CLI wheel sha256 mismatch: expected {asset.sha256}, got {actual_hash}"
            )
        command = ["tool", "install", "--force", str(destination)]
        if callable(uv_executable):
            uv_executable(command)
        else:
            if shutil.which(uv_executable) is None:
                raise SelfUpdateError("uv executable not found")
            completed = subprocess.run(
                [uv_executable, *command], check=False, capture_output=True, text=True
            )
            if completed.returncode != 0:
                raise SelfUpdateError(
                    f"uv tool install failed: {completed.stderr.strip() or completed.stdout.strip()}"
                )
    return Version(asset.version)
